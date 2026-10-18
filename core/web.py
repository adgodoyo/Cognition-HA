"""Web plumbing shared by every app: templates, the current principal, request IDs and
the error contract (JSON for /api/, a readable page for the UI)."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from core import audit
from core.context import PlatformContext, new_request_id
from core.errors import PlatformError, Unauthenticated
from core.identity.base import Principal
from core.money import format_cents
from core.settings import ROOT

templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["money"] = format_cents


def get_platform(request: Request) -> PlatformContext:
    return request.app.state.platform


def optional_principal(request: Request) -> Principal | None:
    if not hasattr(request.state, "principal"):
        request.state.principal = None
        request.state.principal = get_platform(request).identity.current_principal(request)
    return request.state.principal


def require_principal(request: Request) -> Principal:
    principal = optional_principal(request)
    if principal is None:
        demo = get_platform(request).settings.demo_mode
        hint = " or send 'Authorization: Bearer <token>' (get one with: make -s token user=<username>)" if demo else ""
        raise Unauthenticated(f"You are not signed in. Sign in at /signin{hint}.")
    return principal


def is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def payout_totals(platform: PlatformContext) -> tuple[int, int]:
    count = total = 0
    for connector in platform.connectors.values():
        if hasattr(connector, "payout_count"):
            count += connector.payout_count()
            total += connector.total_paid_cents()
    return count, total


def nav_apps(platform: PlatformContext, principal: Principal | None) -> list:
    return [m for m in platform.apps.values() if platform.policy.can_open(principal, m.name)]


def render(request: Request, template: str, status_code: int = 200, **context: Any) -> Response:
    platform = get_platform(request)
    principal = getattr(request.state, "principal", None)
    count, total = payout_totals(platform)
    base = {
        "request": request,
        "platform": platform,
        "settings": platform.settings,
        "principal": principal,
        "role_label": platform.policy.role_label(principal.role) if principal else "",
        "nav_apps": nav_apps(platform, principal),
        "can_read_audit": platform.policy.has(principal, "audit.read"),
        "payout_count": count,
        "payout_total": total,
    }
    return templates.TemplateResponse(request, template, {**base, **context}, status_code=status_code)


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = new_request_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(PlatformError)
    async def platform_error(request: Request, exc: PlatformError):
        platform = get_platform(request)
        principal = getattr(request.state, "principal", None)
        # Every refusal is audited. A signed-out browser being sent to /signin is navigation, not a refusal.
        if is_api(request) or exc.status != 401:
            audit.record(
                platform.db,
                actor=principal.username if principal else "anonymous",
                role=principal.role if principal else None,
                app=exc.app,
                action=exc.action or f"{request.method} {request.url.path}",
                entity=exc.entity,
                outcome="denied",
                detail={"error": exc.code, "message": exc.message, "status": exc.status, **exc.extra},
            )
        if is_api(request):
            return JSONResponse(exc.to_json(), status_code=exc.status)
        if exc.status == 401:
            if request.headers.get("x-live"):
                return Response(status_code=204)
            return RedirectResponse("/signin", status_code=303)
        return render(request, "error.html", status_code=exc.status, error=exc)
