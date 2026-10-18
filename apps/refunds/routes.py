"""Refunds UI and API. Both call the same service functions."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, Header, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from core import approvals
from core.context import PlatformContext
from core.errors import Forbidden
from core.identity.base import Principal
from core.routes import approval_view
from core.web import get_platform, render, require_principal

from apps.refunds import service

router = APIRouter()


class RefundPreviewIn(BaseModel):
    transaction_id: str
    customer_email: str
    amount_cents: int = Field(description="Integer cents, e.g. 120000 for $1,200.00")
    reason: str = ""


class RefundIn(RefundPreviewIn):
    reason: str = Field(min_length=1)


def _payload(body: RefundPreviewIn) -> dict:
    return service.make_payload(body.transaction_id, body.customer_email, body.amount_cents, body.reason)


def _preview_json(result: dict) -> dict:
    txn = result.pop("transaction")
    result["transaction"] = None if txn is None else {
        "id": txn.id, "customer_name": txn.customer_name, "amount_cents": txn.amount_cents,
        "status": txn.status, "refunded_cents": txn.refunded_cents,
    }
    return result


# API

@router.post("/api/refunds/preview", tags=["refunds"])
def api_preview(body: RefundPreviewIn, principal: Principal = Depends(require_principal),
                platform: PlatformContext = Depends(get_platform)):
    """Run the five checks against the ledger and report the risk. Writes nothing."""
    return _preview_json(service.preview(platform, principal, _payload(body)))


@router.post("/api/refunds", tags=["refunds"], status_code=201)
def api_submit(body: RefundIn, response: Response, idempotency_key: str | None = Header(None),
               principal: Principal = Depends(require_principal), platform: PlatformContext = Depends(get_platform)):
    """Submit a refund request. Requires an Idempotency-Key header; the same key returns the same request."""
    approval, created = service.submit(platform, principal, _payload(body), idempotency_key)
    if not created:
        response.status_code = 200
    return approval_view(platform, principal, approval)


# UI

def _page(request: Request, platform: PlatformContext, principal: Principal, *, form: dict | None = None,
          preview: dict | None = None):
    if not platform.policy.can_open(principal, service.APP):
        raise Forbidden("You don't have access to Refunds.", app=service.APP, action="open")
    rows = [approval_view(platform, principal, a) for a in approvals.list_approvals(platform, app=service.APP)]
    form = form or {"transaction_id": "", "customer_email": "", "amount": "", "reason": "",
                    "idempotency_key": secrets.token_urlsafe(16)}
    return render(request, "refunds/index.html", form=form, preview=preview, rows=rows,
                  can_request=platform.policy.has(principal, "refunds.request"))


@router.get("/apps/refunds", include_in_schema=False)
def index(request: Request, principal: Principal = Depends(require_principal),
          platform: PlatformContext = Depends(get_platform)):
    return _page(request, platform, principal)


@router.post("/apps/refunds/check", include_in_schema=False)
def check(request: Request, transaction_id: str = Form(""), customer_email: str = Form(""), amount: str = Form(""),
          reason: str = Form(""), idempotency_key: str = Form(""), principal: Principal = Depends(require_principal),
          platform: PlatformContext = Depends(get_platform)):
    form = {"transaction_id": transaction_id, "customer_email": customer_email, "amount": amount, "reason": reason,
            "idempotency_key": idempotency_key or secrets.token_urlsafe(16)}
    payload = service.payload_from_form(transaction_id, customer_email, amount, reason)
    return _page(request, platform, principal, form=form, preview=service.preview(platform, principal, payload))


@router.post("/apps/refunds", include_in_schema=False)
def submit(transaction_id: str = Form(""), customer_email: str = Form(""), amount: str = Form(""),
           reason: str = Form(""), idempotency_key: str = Form(""), principal: Principal = Depends(require_principal),
           platform: PlatformContext = Depends(get_platform)):
    payload = service.payload_from_form(transaction_id, customer_email, amount, reason)
    approval, _ = service.submit(platform, principal, payload, idempotency_key)
    return RedirectResponse(f"/apps/refunds?submitted={approval.id}", status_code=303)
