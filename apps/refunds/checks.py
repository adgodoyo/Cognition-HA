"""The five checks a refund must pass, each reading the ledger through the connector."""
from __future__ import annotations

from core.connectors.base import Transaction
from core.money import format_cents
from core.verification import Check, CheckResult, Ctx

STATUS_EXPLANATIONS = {
    "pending": "the money hasn't arrived yet",
    "disputed": "the customer opened a chargeback, so the bank is already handling this money",
}


def _transaction(payload: dict, ctx: Ctx) -> Transaction | None:
    key = f"refunds.txn:{payload.get('transaction_id')}"
    if key not in ctx.cache:
        ctx.cache[key] = ctx.connectors["ledger"].get_transaction(payload.get("transaction_id", ""))
    return ctx.cache[key]


def _not_found(payload: dict) -> CheckResult:
    return CheckResult(False, f"Can't check: {payload.get('transaction_id') or 'no transaction'} isn't in the ledger.")


def transaction_exists(payload: dict, ctx: Ctx) -> CheckResult:
    txn = _transaction(payload, ctx)
    if txn is None:
        return CheckResult(False, f"No transaction {payload.get('transaction_id') or '(blank)'} in the ledger.")
    return CheckResult(True, f"Found {txn.id} in the ledger.")


def payment_settled(payload: dict, ctx: Ctx) -> CheckResult:
    txn = _transaction(payload, ctx)
    if txn is None:
        return _not_found(payload)
    if txn.status == "settled":
        return CheckResult(True, "The original payment has settled.")
    reason = STATUS_EXPLANATIONS.get(txn.status, "it can't be refunded in this state")
    return CheckResult(False, f"Status is {txn.status}: {reason}.")


def customer_matches(payload: dict, ctx: Ctx) -> CheckResult:
    txn = _transaction(payload, ctx)
    if txn is None:
        return _not_found(payload)
    given = (payload.get("customer_email") or "").strip()
    if given.casefold() == txn.customer_email.casefold():
        return CheckResult(True, "The email matches the customer on the original payment.")
    return CheckResult(False, f"The email {given or '(blank)'} doesn't match the customer on the original payment.")


def within_window(payload: dict, ctx: Ctx) -> CheckResult:
    txn = _transaction(payload, ctx)
    if txn is None:
        return _not_found(payload)
    window = int(ctx.settings["refund_window_days"])
    age = (ctx.now - txn.captured_at).days
    if age <= window:
        return CheckResult(True, f"Paid {age} days ago, within the {window}-day refund window.")
    return CheckResult(False, f"Paid {age} days ago, outside the {window}-day refund window.")


def amount_refundable(payload: dict, ctx: Ctx) -> CheckResult:
    txn = _transaction(payload, ctx)
    if txn is None:
        return _not_found(payload)
    amount = int(payload.get("amount_cents") or 0)
    open_cents = sum(
        int(r["payload"].get("amount_cents", 0))
        for r in ctx.open_requests
        if r["payload"].get("transaction_id") == txn.id
    )
    refundable = txn.amount_cents - txn.refunded_cents - open_cents
    breakdown = (
        f"Paid {format_cents(txn.amount_cents)} − already refunded {format_cents(txn.refunded_cents)}"
        f" − open requests {format_cents(open_cents)} = {format_cents(refundable)} refundable."
    )
    if amount <= 0:
        return CheckResult(False, f"The amount must be more than zero. {breakdown}")
    if amount > refundable:
        return CheckResult(False, f"{format_cents(amount)} is more than can be refunded. {breakdown}")
    return CheckResult(True, f"{format_cents(amount)} can be refunded. {breakdown}")


def build_checks() -> list[Check]:
    return [
        Check("exists", "Transaction exists in the ledger", transaction_exists),
        Check("settled", "Original payment has settled", payment_settled),
        Check("customer", "Customer matches", customer_matches),
        Check("window", "Within the refund window", within_window),
        Check("amount", "Amount is refundable", amount_refundable),
    ]
