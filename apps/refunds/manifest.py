"""Refunds: what the app declares to the spine."""
from __future__ import annotations

from core.approvals import ActionSpec
from core.registry import AppManifest

from apps.refunds import checks, service
from apps.refunds.routes import router


def build(settings) -> AppManifest:
    cfg = settings.app_settings(service.APP)
    refund = ActionSpec(
        app=service.APP,
        name=service.ACTION,
        request_permission="refunds.request",
        checks=checks.build_checks(),
        risk_level=lambda payload: service.risk_level(payload, cfg),
        execute=service.execute,
        describe=service.describe,
    )
    return AppManifest(
        name=service.APP,
        title="Refunds",
        color=cfg.get("color", "teal"),
        description="Check a refund against the ledger, collect sign-off by risk, pay out exactly once.",
        permissions=["refunds.request", "refunds.approve"],
        actions=[refund],
        router=router,
        nav_path="/apps/refunds",
        connectors_used=["ledger", "payments"],
    )
