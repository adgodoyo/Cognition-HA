"""Mock ledger (system of record for customer payments). The platform reads it read-only;
only the payment processor's settlement writes to it."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.connectors.base import MockSystem, Transaction
from core.db import connect


class LedgerMock(MockSystem):
    name = "ledger"
    tables = (
        """CREATE TABLE transactions (
            id             TEXT PRIMARY KEY,
            customer_name  TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            amount_cents   INTEGER NOT NULL CHECK (amount_cents >= 0),
            status         TEXT NOT NULL CHECK (status IN ('settled', 'pending', 'disputed')),
            captured_at    TEXT NOT NULL,
            refunded_cents INTEGER NOT NULL DEFAULT 0 CHECK (refunded_cents >= 0 AND refunded_cents <= amount_cents)
        )""",
    )

    def load_seed(self, conn, data: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        for t in data.get("transactions", []):
            captured = now - timedelta(days=int(t["captured_days_ago"]))
            conn.execute(
                "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (t["id"], t["customer"], t["email"], int(t["amount_cents"]), t["status"],
                 captured.isoformat(timespec="seconds"), int(t.get("refunded_cents", 0))),
            )

    def _ro(self):
        self.ensure_ready()
        return connect(self.db_path, readonly=True)

    def get_transaction(self, transaction_id: str) -> Transaction | None:
        conn = self._ro()
        try:
            row = conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return Transaction(
            id=row["id"],
            customer_name=row["customer_name"],
            customer_email=row["customer_email"],
            amount_cents=row["amount_cents"],
            status=row["status"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            refunded_cents=row["refunded_cents"],
        )

    def stats(self) -> dict[str, str]:
        conn = self._ro()
        try:
            count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        finally:
            conn.close()
        return {"transactions": str(count), "access": "read-only"}
