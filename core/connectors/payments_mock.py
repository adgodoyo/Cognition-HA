"""Mock payment processor. Honours idempotency keys, refuses over-refunds and settles each
new payout into the ledger by increasing the refunded amount."""
from __future__ import annotations

from core.connectors.base import MockSystem, PaymentError, Payout
from core.connectors.ledger_mock import LedgerMock
from core.db import connect, transaction, utcnow_iso
from core.money import format_cents


class PaymentsMock(MockSystem):
    name = "payments"
    tables = (
        """CREATE TABLE payouts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            transaction_id  TEXT NOT NULL,
            amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
            created_at      TEXT NOT NULL
        )""",
    )

    def __init__(self, db_path, seed_dir, ledger: LedgerMock):
        super().__init__(db_path, seed_dir)
        self.ledger = ledger

    def ensure_ready(self) -> None:
        self.ledger.ensure_ready()  # settlement writes into the ledger's table
        super().ensure_ready()

    @staticmethod
    def _payout(row) -> Payout:
        return Payout(
            id=f"po_{row['id']}",
            transaction_id=row["transaction_id"],
            amount_cents=row["amount_cents"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
        )

    def refund(self, transaction_id: str, amount_cents: int, idempotency_key: str) -> Payout:
        if not idempotency_key:
            raise PaymentError("An idempotency key is required.")
        if not isinstance(amount_cents, int) or amount_cents <= 0:
            raise PaymentError("Refund amount must be a positive number of cents.")
        self.ensure_ready()
        with transaction(self.db_path) as conn:
            existing = conn.execute("SELECT * FROM payouts WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                if existing["transaction_id"] != transaction_id or existing["amount_cents"] != amount_cents:
                    raise PaymentError("This idempotency key was already used for a different refund.")
                return self._payout(existing)
        self._raise_injected_fault()
        with transaction(self.db_path) as conn:
            existing = conn.execute("SELECT * FROM payouts WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                return self._payout(existing)
            txn = conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
            if txn is None:
                raise PaymentError(f"Unknown transaction {transaction_id}.")
            if txn["status"] != "settled":
                raise PaymentError(f"Can't refund a {txn['status']} payment.")
            remaining = txn["amount_cents"] - txn["refunded_cents"]
            if amount_cents > remaining:
                raise PaymentError(
                    f"Refund of {format_cents(amount_cents)} is more than the {format_cents(remaining)} left on the payment."
                )
            cur = conn.execute(
                "INSERT INTO payouts (idempotency_key, transaction_id, amount_cents, created_at) VALUES (?, ?, ?, ?)",
                (idempotency_key, transaction_id, amount_cents, utcnow_iso()),
            )
            # Settlement: the ledger records the refunded money.
            conn.execute(
                "UPDATE transactions SET refunded_cents = refunded_cents + ? WHERE id = ?", (amount_cents, transaction_id)
            )
            row = conn.execute("SELECT * FROM payouts WHERE id = ?", (cur.lastrowid,)).fetchone()
            return self._payout(row)

    def _scalar(self, sql: str) -> int:
        self.ensure_ready()
        conn = connect(self.db_path, readonly=True)
        try:
            return int(conn.execute(sql).fetchone()[0] or 0)
        finally:
            conn.close()

    def payout_count(self) -> int:
        return self._scalar("SELECT COUNT(*) FROM payouts")

    def total_paid_cents(self) -> int:
        return self._scalar("SELECT COALESCE(SUM(amount_cents), 0) FROM payouts")

    def stats(self) -> dict[str, str]:
        return {"payouts": str(self.payout_count()), "total paid": format_cents(self.total_paid_cents())}
