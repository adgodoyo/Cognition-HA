"""Per-request context (request ID) and the runtime container every route reaches through."""
from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.db import Database
    from core.identity.base import IdentityProvider
    from core.policy import Policy
    from core.registry import AppManifest
    from core.settings import Settings

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    _request_id.set(rid)
    return rid


def current_request_id() -> str | None:
    return _request_id.get()


@dataclass
class PlatformContext:
    """Everything the spine needs at runtime. Built once by app_main.create_app."""

    settings: Settings
    policy: Policy
    db: Database
    identity: IdentityProvider
    connectors: dict[str, Any] = field(default_factory=dict)
    apps: dict[str, AppManifest] = field(default_factory=dict)
    loc_stats: list[dict[str, Any]] = field(default_factory=list)

    def action(self, app: str, name: str):
        from core.errors import NotFound

        manifest = self.apps.get(app)
        for spec in manifest.actions if manifest else []:
            if spec.name == name:
                return spec
        raise NotFound(f"Unknown action {app}.{name}.")

    def connectors_for(self, app: str) -> dict[str, Any]:
        """An app only reaches the connectors its manifest declares."""
        manifest = self.apps[app]
        return {name: self.connectors[name] for name in manifest.connectors_used}
