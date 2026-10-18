"""Typed interfaces to external systems. A real integration implements the same protocol
as its mock, so swapping one for the other changes no app code."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

from core.db import connect, transaction


class ConnectorError(Exception):
    """The external system refused or failed. The approval is then marked failed."""


class PaymentError(ConnectorError):
    pass


@dataclass(frozen=True)
class Transaction:
    id: str
    customer_name: str
    customer_email: str
    amount_cents: int
    status: str  # settled | pending | disputed
    captured_at: datetime
    refunded_cents: int


@dataclass(frozen=True)
class Payout:
    id: str
    transaction_id: str
    amount_cents: int
    idempotency_key: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Connector(Protocol):
    name: str
    mode: str  # "mock" or "live"

    def ensure_ready(self) -> None: ...
    def stats(self) -> dict[str, str]: ...


class Ledger(Connector, Protocol):
    def get_transaction(self, transaction_id: str) -> Transaction | None: ...


class PaymentProcessor(Connector, Protocol):
    def refund(self, transaction_id: str, amount_cents: int, idempotency_key: str) -> Payout: ...
    def payout_count(self) -> int: ...
    def total_paid_cents(self) -> int: ...


class MockSystem:
    """Base for a mock external system. State persists in data/ledger.db, next to the other
    mock systems. On first use it creates its tables and seeds itself from seed/<name>.yaml
    (if that file exists), so a reset, which replaces the file, covers it too.

    Failures can be injected with fail_next(); the next call then raises ConnectorError,
    the way a real system's outage would surface."""

    name: str = ""
    mode = "mock"
    tables: tuple[str, ...] = ()

    def __init__(self, db_path: Path, seed_dir: Path):
        self.db_path = db_path
        self.seed_dir = seed_dir

    # Subclasses fill these in

    def load_seed(self, conn, data: dict[str, Any]) -> None:
        pass

    # Lifecycle

    def _is_ready(self) -> bool:
        if not self.db_path.exists():
            return False
        conn = connect(self.db_path, readonly=True)
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = '_mock_systems'"
            ).fetchone()
            return bool(row) and bool(conn.execute("SELECT 1 FROM _mock_systems WHERE name = ?", (self.name,)).fetchone())
        finally:
            conn.close()

    def ensure_ready(self) -> None:
        if self._is_ready():
            return
        with transaction(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS _mock_systems (name TEXT PRIMARY KEY, seeded_at TEXT NOT NULL)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS _mock_faults (id INTEGER PRIMARY KEY AUTOINCREMENT, system TEXT NOT NULL, message TEXT NOT NULL)"
            )
            if conn.execute("SELECT 1 FROM _mock_systems WHERE name = ?", (self.name,)).fetchone():
                return
            for ddl in self.tables:
                conn.execute(ddl)
            seed_file = self.seed_dir / f"{self.name}.yaml"
            if seed_file.exists():
                with seed_file.open() as fh:
                    self.load_seed(conn, yaml.safe_load(fh) or {})
            conn.execute("INSERT INTO _mock_systems (name, seeded_at) VALUES (?, datetime('now'))", (self.name,))

    # Failure injection

    def fail_next(self, message: str) -> None:
        self.ensure_ready()
        with transaction(self.db_path) as conn:
            conn.execute("INSERT INTO _mock_faults (system, message) VALUES (?, ?)", (self.name, message))

    def _raise_injected_fault(self) -> None:
        with transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, message FROM _mock_faults WHERE system = ? ORDER BY id LIMIT 1", (self.name,)
            ).fetchone()
            if row:
                conn.execute("DELETE FROM _mock_faults WHERE id = ?", (row["id"],))
        if row:
            raise ConnectorError(f"{self.name} is unavailable: {row['message']}")
