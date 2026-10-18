"""The checks a flag change must pass, each reading the flag service through the connector."""
from __future__ import annotations

from core.connectors.flags_mock import Flag
from core.verification import Check, CheckResult, Ctx

from apps.flags.service import env_label, state_text


def _flag(payload: dict, ctx: Ctx) -> Flag | None:
    key = f"flags.flag:{payload.get('flag')}"
    if key not in ctx.cache:
        ctx.cache[key] = ctx.connectors["flags"].get_flag(payload.get("flag", ""))
    return ctx.cache[key]


def flag_exists(payload: dict, ctx: Ctx) -> CheckResult:
    flag = _flag(payload, ctx)
    if flag is None:
        return CheckResult(False, f"There's no flag called {payload.get('flag') or '(blank)'}.")
    return CheckResult(True, f"Found the flag {flag.name}.")


def environment_exists(payload: dict, ctx: Ctx) -> CheckResult:
    env = payload.get("environment") or ""
    flag = _flag(payload, ctx)
    if flag is None:
        return CheckResult(False, "Can't check the environment: the flag doesn't exist.")
    if env not in flag.environments or env not in (ctx.settings.get("environments") or {}):
        return CheckResult(False, f"{env or '(blank)'} isn't one of this flag's environments.")
    return CheckResult(True, f"{env_label(ctx.settings, env)} exists for this flag.")


def rollout_in_range(payload: dict, ctx: Ctx) -> CheckResult:
    percent = int(payload.get("rollout_percent", -1))
    if 0 <= percent <= 100:
        return CheckResult(True, f"{percent}% is a valid rollout.")
    return CheckResult(False, f"{percent}% isn't a valid rollout: it must be between 0 and 100.")


def changes_something(payload: dict, ctx: Ctx) -> CheckResult:
    flag = _flag(payload, ctx)
    current = flag.environments.get(payload.get("environment") or "") if flag else None
    if current is None:
        return CheckResult(False, "Can't compare: the flag or environment doesn't exist.")
    wanted = (bool(payload.get("enabled")), int(payload.get("rollout_percent", 0)))
    now = state_text(current.enabled, current.rollout_percent)
    if (current.enabled, current.rollout_percent) == wanted:
        return CheckResult(False, f"Nothing would change: it's already {now}.")
    return CheckResult(True, f"Changes it from {now} to {state_text(*wanted)}.")


def build_checks() -> list[Check]:
    return [
        Check("flag", "The flag exists", flag_exists),
        Check("environment", "The environment exists", environment_exists),
        Check("rollout", "Rollout is between 0 and 100%", rollout_in_range),
        Check("changes", "The change actually changes something", changes_something),
    ]
