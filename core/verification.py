"""Verification: an app's checks run against systems of record before anything moves."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable

from core.db import utcnow


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    detail: str


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    run: Callable[[dict, "Ctx"], CheckResult]


@dataclass
class Ctx:
    """What a check (or an action's execute) may use."""

    app: str
    settings: dict[str, Any]
    connectors: dict[str, Any]
    now: datetime
    open_requests: list[dict[str, Any]]
    cache: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckOutcome:
    key: str
    label: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def open_requests(conn: sqlite3.Connection, app: str) -> list[dict[str, Any]]:
    """The app's requests that are pending or approved but not yet executed."""
    rows = conn.execute(
        "SELECT id, action, payload FROM approvals WHERE app = ? AND status IN ('pending', 'approved')", (app,)
    ).fetchall()
    return [{"id": r["id"], "action": r["action"], "payload": json.loads(r["payload"])} for r in rows]


def build_ctx(platform, app: str, conn: sqlite3.Connection) -> Ctx:
    return Ctx(
        app=app,
        settings=platform.settings.app_settings(app),
        connectors=platform.connectors_for(app),
        now=utcnow(),
        open_requests=open_requests(conn, app),
    )


def run_checks(checks: list[Check], payload: dict, ctx: Ctx) -> list[CheckOutcome]:
    outcomes = []
    for check in checks:
        try:
            result = check.run(payload, ctx)
        except Exception as exc:  # a check that can't run is a failed check, never a pass
            result = CheckResult(False, f"This check could not run: {exc}")
        outcomes.append(CheckOutcome(check.key, check.label, bool(result.passed), result.detail))
    return outcomes
