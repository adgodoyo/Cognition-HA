"""Feature flags: what the app declares to the spine."""
from __future__ import annotations

from core.approvals import ActionSpec
from core.connectors.flags_mock import FlagsMock
from core.registry import AppManifest

from apps.flags import checks, service
from apps.flags.routes import router


def build(settings) -> AppManifest:
    cfg = settings.app_settings(service.APP)
    flags = FlagsMock(settings.ledger_db, settings.seed_dir)
    change = ActionSpec(
        app=service.APP,
        name=service.ACTION,
        request_permission="flags.change",
        checks=checks.build_checks(),
        risk_level=lambda payload: service.risk_level(payload, cfg),
        execute=service.execute,
        describe=lambda payload: service.describe(payload, cfg, flags),
    )
    return AppManifest(
        name=service.APP,
        title="Feature flags",
        color=cfg.get("color", "purple"),
        description="Turn features on per environment; risky production changes collect sign-off.",
        permissions=["flags.change", "flags.approve"],
        actions=[change],
        router=router,
        nav_path="/apps/flags",
        connectors_used=["flags"],
        connectors={flags.name: flags},
    )
