"""SQLite access for the platform's own data (data/platform.db): users, approvals,
signatures and the audit log. Mock external systems live in data/ledger.db (core/connectors/)."""
from __future__ import annotations

import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    username   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    title      TEXT NOT NULL,
    department TEXT NOT NULL,
    role       TEXT NOT NULL,
    dev_token  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS approvals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    app             TEXT NOT NULL,
    action          TEXT NOT NULL,
    payload         TEXT NOT NULL,          -- JSON
    description     TEXT NOT NULL,
    risk            TEXT NOT NULL,          -- low | elevated | high
    requirements    TEXT NOT NULL,          -- JSON list of signer types, in order
    status          TEXT NOT NULL,          -- pending | approved | executed | failed | rejected
    requester       TEXT NOT NULL REFERENCES users(username),
    idempotency_key TEXT NOT NULL UNIQUE,
    request_hash    TEXT NOT NULL,
    result          TEXT,                   -- JSON returned by the action's execute
    error           TEXT,
    reject_reason   TEXT,
    rejected_by     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_signatures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_id INTEGER NOT NULL REFERENCES approvals(id),
    requirement TEXT NOT NULL,              -- signer type key
    signer      TEXT NOT NULL REFERENCES users(username),
    role        TEXT NOT NULL,
    signed_at   TEXT NOT NULL,
    UNIQUE (approval_id, requirement)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    actor      TEXT NOT NULL,
    role       TEXT,
    app        TEXT,
    action     TEXT NOT NULL,
    entity     TEXT,
    outcome    TEXT NOT NULL CHECK (outcome IN ('allowed', 'denied', 'checked', 'executed', 'failed')),
    before     TEXT,                        -- JSON
    after      TEXT,                        -- JSON
    detail     TEXT,                        -- JSON
    request_id TEXT
);

CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit log is append-only');
END;
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Open a connection in autocommit mode; callers use explicit transactions."""
    if readonly:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10, isolation_level=None)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=10, isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    """A write transaction that takes the write lock up front (BEGIN IMMEDIATE),
    so two concurrent requests can't both read the same state and then both write."""
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def remove_db_files(path: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self.path)
        try:
            yield conn
        finally:
            conn.close()

    def write(self):
        return transaction(self.path)

    def exists(self) -> bool:
        return self.path.exists()

    def init_schema(self) -> None:
        with self.read() as conn:
            conn.executescript(SCHEMA)

    def meta(self, key: str) -> str | None:
        with self.read() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.read() as conn:
            return conn.execute(sql, tuple(params)).fetchall()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self.read() as conn:
            return conn.execute(sql, tuple(params)).fetchone()

    def seed(self, users: list[dict[str, Any]], known_roles: Iterable[str]) -> None:
        """Fresh platform data: schema, users with new random dev tokens, a new session epoch."""
        known = set(known_roles)
        for user in users:
            if user["role"] not in known:
                raise ValueError(f"Seed user {user['username']!r} has role {user['role']!r}, which policy.yaml doesn't define.")
        self.init_schema()
        with self.write() as conn:
            conn.executemany(
                "INSERT INTO users (username, name, title, department, role, dev_token) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (u["username"], u["name"], u["title"], u["department"], u["role"], secrets.token_urlsafe(24))
                    for u in users
                ],
            )
            # Sessions carry this epoch; a reset changes it, which signs everyone out.
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('session_epoch', ?)", (secrets.token_hex(8),)
            )


def load_seed_users(seed_dir: Path) -> list[dict[str, Any]]:
    with (seed_dir / "users.yaml").open() as fh:
        return (yaml.safe_load(fh) or {}).get("users", [])


def reset_all(settings, policy, connectors: dict[str, Any]) -> None:
    """Replace both database files with fresh copies built from seed/.
    Audit rows are never edited: the demo databases are replaced as a whole."""
    remove_db_files(settings.platform_db)
    remove_db_files(settings.ledger_db)
    Database(settings.platform_db).seed(load_seed_users(settings.seed_dir), policy.roles.keys())
    for connector in connectors.values():
        connector.ensure_ready()
