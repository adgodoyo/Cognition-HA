"""Feature flags UI and API. Both submit through core.approvals."""
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

from apps.flags import service

router = APIRouter()


class FlagChangeIn(BaseModel):
    flag: str
    environment: str
    enabled: bool
    rollout_percent: int = Field(description="0-100")


def _require_open(platform: PlatformContext, principal: Principal) -> None:
    if not platform.policy.can_open(principal, service.APP):
        raise Forbidden("You don't have access to Feature flags.", app=service.APP, action="open")


def _pending_by_cell(platform: PlatformContext, principal: Principal) -> dict[tuple[str, str], dict]:
    pending: dict[tuple[str, str], dict] = {}
    for a in approvals.list_approvals(platform, app=service.APP, statuses=("pending",)):
        pending.setdefault((a.payload["flag"], a.payload["environment"]), approval_view(platform, principal, a))
    return pending


def _cfg(platform: PlatformContext) -> dict:
    return platform.settings.app_settings(service.APP)


def _signers(platform: PlatformContext, a: approvals.Approval) -> str:
    return ", then ".join(approvals.signer_label(platform, a.app, r) for r in a.requirements)


# API

@router.get("/api/flags", tags=["flags"])
def api_flags(principal: Principal = Depends(require_principal), platform: PlatformContext = Depends(get_platform)):
    """Every flag with its state per environment, plus any change waiting for signatures."""
    _require_open(platform, principal)
    cfg, pending = _cfg(platform), _pending_by_cell(platform, principal)
    return [
        {
            "flag": f.key, "name": f.name, "description": f.description,
            "environments": {
                env: {"label": service.env_label(cfg, env), "enabled": s.enabled, "rollout_percent": s.rollout_percent,
                      "pending": pending.get((f.key, env))}
                for env, s in f.environments.items()
            },
        }
        for f in platform.connectors_for(service.APP)["flags"].get_flags()
    ]


@router.post("/api/flags/changes", tags=["flags"], status_code=201)
def api_change(body: FlagChangeIn, response: Response, idempotency_key: str | None = Header(None),
               principal: Principal = Depends(require_principal), platform: PlatformContext = Depends(get_platform)):
    """Request a flag change. Requires an Idempotency-Key header; the same key returns the same request."""
    payload = service.make_payload(body.flag, body.environment, body.enabled, body.rollout_percent)
    approval, created = approvals.submit(platform, principal, service.APP, service.ACTION, payload, idempotency_key)
    if not created:
        response.status_code = 200
    return approval_view(platform, principal, approval)


# UI

@router.get("/apps/flags", include_in_schema=False)
def index(request: Request, submitted: int | None = None, principal: Principal = Depends(require_principal),
          platform: PlatformContext = Depends(get_platform)):
    _require_open(platform, principal)
    cfg, pending = _cfg(platform), _pending_by_cell(platform, principal)
    environments = cfg.get("environments") or {}
    rows = [
        {"flag": f, "cells": [{"env": env, "state": f.environments.get(env), "pending": pending.get((f.key, env)),
                               "key": secrets.token_urlsafe(16)} for env in environments]}
        for f in platform.connectors_for(service.APP)["flags"].get_flags()
    ]
    flash = None
    a = approvals.get(platform, submitted) if submitted else None
    if a and a.app == service.APP:
        if a.status == "executed":
            flash = {"kind": "ok", "text": f"Applied: {a.description}"}
        elif a.status == "pending":
            flash = {"kind": "pending", "text": f"Sent for approval: {_signers(platform, a)}", "detail": a.description}
        else:
            flash = {"kind": "bad", "text": f"{approvals.status_text(platform, a)}: {a.description}", "detail": a.error}
    requests = [approval_view(platform, principal, x) for x in approvals.list_approvals(platform, app=service.APP)]
    return render(request, "flags/index.html", rows=rows, environments=environments, flash=flash,
                  requests=requests, can_change=platform.policy.has(principal, "flags.change"))


@router.post("/apps/flags/changes", include_in_schema=False)
def change(flag: str = Form(""), environment: str = Form(""), enabled: str | None = Form(None),
           rollout_percent: str = Form(""), idempotency_key: str = Form(""),
           principal: Principal = Depends(require_principal), platform: PlatformContext = Depends(get_platform)):
    payload = service.payload_from_form(flag, environment, enabled, rollout_percent)
    approval, _ = approvals.submit(platform, principal, service.APP, service.ACTION, payload, idempotency_key)
    return RedirectResponse(f"/apps/flags?submitted={approval.id}", status_code=303)
