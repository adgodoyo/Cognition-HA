"""Routes the spine owns: sign-in, home, inbox, audit log, platform page, reset, and the
approval API that every app shares."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from core import approvals, audit
from core.approvals import SIGNER_TYPES, Approval
from core.context import PlatformContext
from core.db import reset_all
from core.errors import Forbidden
from core.identity.base import Principal
from core.policy import RISK_LEVELS
from core.registry import CAPABILITIES
from core.web import get_platform, optional_principal, render, require_principal

router = APIRouter()


def _people(platform: PlatformContext) -> dict[str, Any]:
    return {r["username"]: r for r in platform.db.query("SELECT username, name FROM users")}


def approval_view(platform: PlatformContext, principal: Principal | None, a: Approval,
                  people: dict | None = None) -> dict[str, Any]:
    """Everything a template or API client needs about a request, decided by the core."""
    people = people if people is not None else _people(platform)
    ok, reason = approvals.can_sign(platform, principal, a)
    manifest = platform.apps.get(a.app)
    requester = people.get(a.requester)
    return {
        "id": a.id,
        "app": a.app,
        "app_title": manifest.title if manifest else a.app,
        "app_color": manifest.color if manifest else "gray",
        "action": a.action,
        "description": a.description,
        "payload": a.payload,
        "risk": a.risk,
        "status": a.status,
        "status_text": approvals.status_text(platform, a),
        "progress": approvals.progress_text(platform, a),
        "requester": a.requester,
        "requester_name": requester["name"] if requester else a.requester,
        "can_sign": ok,
        "can_sign_reason": reason,
        "result": a.result,
        "error": a.error,
        "reject_reason": a.reject_reason,
        "created_at": a.created_at,
    }


def _safe_next(target: str | None, default: str) -> str:
    return target if target and target.startswith("/") and not target.startswith("//") else default


INBOX_RECENT = 10


# Sign-in

@router.get("/signin", include_in_schema=False)
def signin_page(request: Request, platform: PlatformContext = Depends(get_platform)):
    optional_principal(request)
    groups: dict[str, list] = defaultdict(list)
    if platform.settings.demo_mode:
        for person in platform.identity.people():
            can, cannot = platform.policy.can_cannot(person.role)
            groups[person.department].append(
                {"p": person, "role_label": platform.policy.role_label(person.role), "can": can, "cannot": cannot}
            )
    return render(request, "signin.html", groups=dict(groups))


@router.post("/signin", include_in_schema=False)
def signin(request: Request, username: str = Form(...), platform: PlatformContext = Depends(get_platform)):
    platform.identity.sign_in(request, username)
    return RedirectResponse("/", status_code=303)


@router.post("/signout", include_in_schema=False)
def signout(request: Request, platform: PlatformContext = Depends(get_platform)):
    platform.identity.sign_out(request)
    return RedirectResponse("/signin", status_code=303)


# Pages

@router.get("/", include_in_schema=False)
def home(request: Request, platform: PlatformContext = Depends(get_platform)):
    principal = optional_principal(request)
    if principal is None:
        return render(request, "welcome.html", apps=list(platform.apps.values()))
    tiles = [{"m": m, "open": platform.policy.can_open(principal, m.name)} for m in platform.apps.values()]
    can_sign_any = approvals.can_sign_anything(platform, principal)
    waiting = len(approvals.waiting_for(platform, principal)) if can_sign_any else 0
    activity = audit.events(platform.db, actor=principal.username, limit=8)
    return render(request, "home.html", tiles=tiles, can_sign_any=can_sign_any, waiting=waiting, activity=activity)


@router.get("/inbox", include_in_schema=False)
def inbox(request: Request, principal: Principal = Depends(require_principal),
          platform: PlatformContext = Depends(get_platform)):
    people = _people(platform)
    waiting = [approval_view(platform, principal, a, people) for a in approvals.waiting_for(platform, principal)]
    mine = [approval_view(platform, principal, a, people)
            for a in approvals.list_approvals(platform, requester=principal.username)[:INBOX_RECENT]]
    decided = [approval_view(platform, principal, a, people)
               for a in approvals.list_approvals(platform, statuses=("executed", "failed", "rejected"))
               if approvals.oversees(platform, principal, a.app)][:INBOX_RECENT]
    return render(request, "inbox.html", waiting=waiting, mine=mine, decided=decided,
                  oversees_any=approvals.can_sign_anything(platform, principal))


@router.get("/audit", include_in_schema=False)
def audit_log(request: Request, app: str | None = None, principal: Principal = Depends(require_principal),
              platform: PlatformContext = Depends(get_platform)):
    if not platform.policy.has(principal, "audit.read"):
        raise Forbidden(f"Your role ({platform.policy.role_label(principal.role)}) does not have the permission: "
                        f"{platform.policy.permissions.get('audit.read', 'audit.read')}.", action="audit.view")
    rows = audit.events(platform.db, app=app or None)
    return render(request, "audit.html", rows=rows, app_filter=app or "")


@router.get("/platform", include_in_schema=False)
def platform_page(request: Request, platform: PlatformContext = Depends(get_platform)):
    optional_principal(request)
    apps = list(platform.apps.values())
    capabilities = [{"c": c, "apps": {m.name: c.used_by(m) for m in apps}} for c in CAPABILITIES]
    app_colors = {m.name: m.color for m in apps}
    requirements = [
        {
            "level": level,
            "steps": platform.policy.requirements_for(level),
            "per_app": {m.name: approvals.needs_text(platform, m.name, platform.policy.requirements_for(level)) for m in apps},
        }
        for level in RISK_LEVELS
    ]
    connectors = [
        {"name": name, "mode": c.mode, "stats": c.stats(),
         "used_by": [m.title for m in apps if name in m.connectors_used]}
        for name, c in platform.connectors.items()
    ]
    core_total = sum(r["lines"] for r in platform.loc_stats if r["group"] == "core")
    return render(
        request, "platform.html", apps=apps, capabilities=capabilities, app_colors=app_colors,
        requirements=requirements, connectors=connectors, signer_types=SIGNER_TYPES, core_total=core_total,
    )


@router.post("/admin/reset", include_in_schema=False)
def reset(request: Request, platform: PlatformContext = Depends(get_platform)):
    if not platform.settings.demo_mode:
        raise HTTPException(status_code=404)
    reset_all(platform.settings, platform.policy, platform.connectors)
    request.session.clear()
    return RedirectResponse("/signin", status_code=303)


# Approvals, shared by every app

@router.get("/api/me", tags=["identity"])
def me(principal: Principal = Depends(require_principal), platform: PlatformContext = Depends(get_platform)):
    """Who the server thinks you are. The role comes from the users table, never from the client."""
    return {**principal.to_dict(), "role_label": platform.policy.role_label(principal.role)}


@router.post("/api/approvals/{approval_id}/sign", tags=["approvals"])
def api_sign(approval_id: int, principal: Principal = Depends(require_principal),
             platform: PlatformContext = Depends(get_platform)):
    """Sign the next step of a request. The last signature executes it, exactly once."""
    a = approvals.sign(platform, principal, approval_id)
    return approval_view(platform, principal, a)


@router.post("/api/approvals/{approval_id}/reject", tags=["approvals"])
def api_reject(approval_id: int, reason: str = Body("", embed=True), principal: Principal = Depends(require_principal),
               platform: PlatformContext = Depends(get_platform)):
    """Reject a request. A reason is required."""
    a = approvals.reject(platform, principal, approval_id, reason)
    return approval_view(platform, principal, a)


@router.post("/approvals/{approval_id}/sign", include_in_schema=False)
def ui_sign(approval_id: int, next: str | None = Form(None), principal: Principal = Depends(require_principal),
            platform: PlatformContext = Depends(get_platform)):
    approvals.sign(platform, principal, approval_id)
    return RedirectResponse(_safe_next(next, "/inbox"), status_code=303)


@router.post("/approvals/{approval_id}/reject", include_in_schema=False)
def ui_reject(approval_id: int, reason: str = Form(""), next: str | None = Form(None),
              principal: Principal = Depends(require_principal), platform: PlatformContext = Depends(get_platform)):
    approvals.reject(platform, principal, approval_id, reason)
    return RedirectResponse(_safe_next(next, "/inbox"), status_code=303)
