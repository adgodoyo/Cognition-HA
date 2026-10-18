"""Settings: read config/settings.yaml and config/policy.yaml, plus a few environment variables."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    platform_name: str
    live_refresh_seconds: int
    identity_provider: str
    installed_apps: list[str]
    apps: dict[str, dict[str, Any]]
    policy: dict[str, Any]
    data_dir: Path
    platform_db: Path
    ledger_db: Path
    seed_dir: Path
    demo_mode: bool
    session_secret: str
    root: Path = field(default=ROOT)

    def app_settings(self, app: str) -> dict[str, Any]:
        return dict(self.apps.get(app, {}))


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def load_settings(
    config_dir: Path | None = None,
    *,
    data_dir: Path | None = None,
    seed_dir: Path | None = None,
    demo_mode: bool | None = None,
) -> Settings:
    """Load settings. Keyword arguments override config (used by tests)."""
    config_dir = config_dir or ROOT / "config"
    raw = _load_yaml(config_dir / "settings.yaml")
    policy = _load_yaml(config_dir / "policy.yaml")
    storage = raw.get("storage", {})
    platform = raw.get("platform", {})

    resolved_data = Path(data_dir) if data_dir else ROOT / storage.get("data_dir", "data")
    resolved_seed = Path(seed_dir) if seed_dir else ROOT / storage.get("seed_dir", "seed")

    return Settings(
        platform_name=platform.get("name", "Internal Tools"),
        live_refresh_seconds=int(platform.get("live_refresh_seconds", 2)),
        identity_provider=raw.get("identity", {}).get("provider", "mock"),
        installed_apps=list(raw.get("installed_apps", [])),
        apps=raw.get("apps", {}) or {},
        policy=policy,
        data_dir=resolved_data,
        platform_db=resolved_data / storage.get("platform_db", "platform.db"),
        ledger_db=resolved_data / storage.get("ledger_db", "ledger.db"),
        seed_dir=resolved_seed,
        demo_mode=_truthy(os.environ.get("DEMO_MODE")) if demo_mode is None else demo_mode,
        session_secret=os.environ.get("SESSION_SECRET") or secrets.token_urlsafe(32),
    )
