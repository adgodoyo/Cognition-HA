"""Feature flag service: typed interface plus its mock. The mock keeps state in data/ledger.db
with the other mock external systems and seeds itself from seed/flags.yaml on first use."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.connectors.base import Connector, ConnectorError, MockSystem
from core.db import connect, transaction, utcnow_iso


@dataclass(frozen=True)
class FlagState:
    enabled: bool
    rollout_percent: int


@dataclass(frozen=True)
class Flag:
    key: str
    name: str
    description: str
    environments: dict[str, FlagState]


@dataclass(frozen=True)
class FlagChange:
    id: str
    flag: str
    environment: str
    before: FlagState
    after: FlagState
    idempotency_key: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FlagServiceConnector(Connector, Protocol):
    def get_flags(self) -> list[Flag]: ...
    def get_flag(self, key: str) -> Flag | None: ...
    def apply_change(self, flag: str, environment: str, enabled: bool, rollout_percent: int,
                     idempotency_key: str) -> FlagChange: ...
    def change_count(self) -> int: ...


class FlagsMock(MockSystem):
    name = "flags"
    tables = (
        """CREATE TABLE flags (
            key         TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT NOT NULL,
            position    INTEGER NOT NULL
        )""",
        """CREATE TABLE flag_states (
            flag            TEXT NOT NULL REFERENCES flags(key),
            environment     TEXT NOT NULL,
            enabled         INTEGER NOT NULL CHECK (enabled IN (0, 1)),
            rollout_percent INTEGER NOT NULL CHECK (rollout_percent BETWEEN 0 AND 100),
            PRIMARY KEY (flag, environment)
        )""",
        """CREATE TABLE flag_changes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            flag            TEXT NOT NULL,
            environment     TEXT NOT NULL,
            before          TEXT NOT NULL,
            after           TEXT NOT NULL,
            created_at      TEXT NOT NULL
        )""",
    )

    def load_seed(self, conn, data: dict[str, Any]) -> None:
        for position, f in enumerate(data.get("flags", [])):
            conn.execute("INSERT INTO flags VALUES (?, ?, ?, ?)", (f["id"], f["name"], f.get("description", ""), position))
            for env, state in (f.get("environments") or {}).items():
                conn.execute("INSERT INTO flag_states VALUES (?, ?, ?, ?)",
                             (f["id"], env, int(bool(state["enabled"])), int(state["rollout_percent"])))

    def _ro(self):
        self.ensure_ready()
        return connect(self.db_path, readonly=True)

    @staticmethod
    def _flags(conn, where: str = "", params: tuple = ()) -> list[Flag]:
        flags = conn.execute(f"SELECT * FROM flags {where} ORDER BY position", params).fetchall()
        out = []
        for f in flags:
            states = conn.execute("SELECT * FROM flag_states WHERE flag = ? ORDER BY rowid", (f["key"],)).fetchall()
            out.append(Flag(f["key"], f["name"], f["description"],
                            {s["environment"]: FlagState(bool(s["enabled"]), s["rollout_percent"]) for s in states}))
        return out

    def get_flags(self) -> list[Flag]:
        conn = self._ro()
        try:
            return self._flags(conn)
        finally:
            conn.close()

    def get_flag(self, key: str) -> Flag | None:
        conn = self._ro()
        try:
            found = self._flags(conn, "WHERE key = ?", (key,))
        finally:
            conn.close()
        return found[0] if found else None

    @staticmethod
    def _change(row) -> FlagChange:
        return FlagChange(f"fc_{row['id']}", row["flag"], row["environment"],
                          FlagState(**json.loads(row["before"])), FlagState(**json.loads(row["after"])),
                          row["idempotency_key"], row["created_at"])

    def apply_change(self, flag: str, environment: str, enabled: bool, rollout_percent: int,
                     idempotency_key: str) -> FlagChange:
        if not idempotency_key:
            raise ConnectorError("An idempotency key is required.")
        if not 0 <= int(rollout_percent) <= 100:
            raise ConnectorError("Rollout must be between 0 and 100 percent.")
        self.ensure_ready()
        after = FlagState(bool(enabled), int(rollout_percent))
        with transaction(self.db_path) as conn:
            existing = conn.execute("SELECT * FROM flag_changes WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                change = self._change(existing)
                if (change.flag, change.environment, change.after) != (flag, environment, after):
                    raise ConnectorError("This idempotency key was already used for a different change.")
                return change
        self._raise_injected_fault()
        with transaction(self.db_path) as conn:
            existing = conn.execute("SELECT * FROM flag_changes WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                return self._change(existing)
            row = conn.execute("SELECT * FROM flag_states WHERE flag = ? AND environment = ?", (flag, environment)).fetchone()
            if row is None:
                raise ConnectorError(f"Unknown flag {flag!r} in environment {environment!r}.")
            before = FlagState(bool(row["enabled"]), row["rollout_percent"])
            conn.execute("UPDATE flag_states SET enabled = ?, rollout_percent = ? WHERE flag = ? AND environment = ?",
                         (int(after.enabled), after.rollout_percent, flag, environment))
            cur = conn.execute(
                "INSERT INTO flag_changes (idempotency_key, flag, environment, before, after, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (idempotency_key, flag, environment, json.dumps(asdict(before)), json.dumps(asdict(after)), utcnow_iso()),
            )
            return self._change(conn.execute("SELECT * FROM flag_changes WHERE id = ?", (cur.lastrowid,)).fetchone())

    def change_count(self) -> int:
        conn = self._ro()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM flag_changes").fetchone()[0])
        finally:
            conn.close()

    def stats(self) -> dict[str, str]:
        return {"flags": str(len(self.get_flags())), "changes applied": str(self.change_count())}
