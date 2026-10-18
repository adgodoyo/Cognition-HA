"""Refunds: turn input into a payload, decide its risk from config, and execute through the
payment processor. Everything else (permissions, checks, signatures, audit) is the spine's."""
from __future__ import annotations

from typing import Any

from core import approvals
from core.errors import InvalidInput
from core.identity.base import Principal
from core.money import dollars_to_cents, format_cents
from core.verification import Ctx

APP = "refunds"
ACTION = "refund"


def make_payload(transaction_id: str, customer_email: str, amount_cents: int, reason: str) -> dict[str, Any]:
    return {
        "transaction_id": (transaction_id or "").strip(),
        "customer_email": (customer_email or "").strip(),
        "amount_cents": int(amount_cents),
        "reason": (reason or "").strip(),
    }


def payload_from_form(transaction_id: str, customer_email: str, amount: str, reason: str) -> dict[str, Any]:
    try:
        cents = dollars_to_cents(amount)
    except ValueError as exc:
        raise InvalidInput(str(exc), app=APP, action=f"{ACTION}.request") from exc
    return make_payload(transaction_id, customer_email, cents, reason)


def risk_level(payload: dict, cfg: dict) -> str:
    amount = int(payload["amount_cents"])
    if amount <= int(cfg["elevated_above_cents"]):
        return "low"
    if amount <= int(cfg["high_above_cents"]):
        return "elevated"
    return "high"


def describe(payload: dict) -> str:
    return f"Refund {format_cents(payload['amount_cents'])} on {payload['transaction_id']}"


def execute(payload: dict, idempotency_key: str, ctx: Ctx) -> dict[str, Any]:
    ledger, payments = ctx.connectors["ledger"], ctx.connectors["payments"]
    before = ledger.get_transaction(payload["transaction_id"])
    payout = payments.refund(payload["transaction_id"], int(payload["amount_cents"]), idempotency_key)
    after = ledger.get_transaction(payload["transaction_id"])
    return {
        "payout": payout.to_dict(),
        "ledger_refunded_before_cents": before.refunded_cents if before else None,
        "ledger_refunded_after_cents": after.refunded_cents if after else None,
    }


def _require_reason(payload: dict) -> None:
    if not payload["reason"]:
        raise InvalidInput("Give a reason for the refund.", app=APP, action=f"{ACTION}.request")


def preview(platform, principal: Principal, payload: dict) -> dict[str, Any]:
    result = approvals.preview(platform, principal, APP, ACTION, payload)
    txn = platform.connectors_for(APP)["ledger"].get_transaction(payload["transaction_id"])
    result["transaction"] = txn
    return result


def submit(platform, principal: Principal, payload: dict, idempotency_key: str | None):
    _require_reason(payload)
    return approvals.submit(platform, principal, APP, ACTION, payload, idempotency_key)
