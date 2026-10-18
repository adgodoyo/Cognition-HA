"""Feature flags: turn input into a payload, decide its risk from config, describe it for
people, and apply it through the flag service. Permissions, signatures and audit are the spine's."""
from __future__ import annotations

from typing import Any

from core.errors import InvalidInput
from core.verification import Ctx

APP = "flags"
ACTION = "change"


def make_payload(flag: str, environment: str, enabled: bool, rollout_percent: int) -> dict[str, Any]:
    return {
        "flag": (flag or "").strip(),
        "environment": (environment or "").strip(),
        "enabled": bool(enabled),
        "rollout_percent": int(rollout_percent),
    }


def payload_from_form(flag: str, environment: str, enabled: str | None, rollout_percent: str) -> dict[str, Any]:
    try:
        percent = int(str(rollout_percent).strip().rstrip("%"))
    except ValueError as exc:
        raise InvalidInput("Rollout must be a whole number of percent.", app=APP, action=f"{ACTION}.request") from exc
    return make_payload(flag, environment, enabled in ("on", "true", "1"), percent)


def env_label(cfg: dict, environment: str) -> str:
    return (cfg.get("environments") or {}).get(environment, environment)


def state_text(enabled: bool, rollout_percent: int) -> str:
    return f"on at {rollout_percent}%" if enabled else "off"


def risk_level(payload: dict, cfg: dict) -> str:
    if payload["environment"] != cfg["production_environment"]:
        return "low"
    if payload["enabled"] and int(payload["rollout_percent"]) >= int(cfg["full_rollout_percent"]):
        return "high"
    return "elevated"


def describe(payload: dict, cfg: dict, flags) -> str:
    flag = flags.get_flag(payload["flag"])
    name = flag.name if flag else payload["flag"]
    target = state_text(payload["enabled"], int(payload["rollout_percent"]))
    return f"{name}: {env_label(cfg, payload['environment'])} → {target}"


def execute(payload: dict, idempotency_key: str, ctx: Ctx) -> dict[str, Any]:
    change = ctx.connectors["flags"].apply_change(
        payload["flag"], payload["environment"], payload["enabled"], int(payload["rollout_percent"]), idempotency_key
    )
    return {"change": change.to_dict()}
