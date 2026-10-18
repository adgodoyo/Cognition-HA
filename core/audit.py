"""Audit trail: one append-only table. record() is the only writer; the database itself
refuses UPDATE and DELETE on audit rows (see the triggers in core/db.py)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from core.context import current_request_id
from core.db import Database, utcnow_iso

OUTCOMES = ("allowed", "denied", "checked", "executed", "failed")


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, default=str, sort_keys=True)


def record(
    db: Database,
    *,
    actor: str,
    role: str | None,
    action: str,
    outcome: str,
    app: str | None = None,
    entity: str | None = None,
    before: Any = None,
    after: Any = None,
    detail: Any = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown audit outcome {outcome!r}.")
    row = (utcnow_iso(), actor, role, app, action, entity, outcome, _json(before), _json(after), _json(detail), current_request_id())
    sql = (
        "INSERT INTO audit_events (ts, actor, role, app, action, entity, outcome, before, after, detail, request_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    if conn is not None:
        conn.execute(sql, row)
    else:
        with db.write() as own:
            own.execute(sql, row)


def events(db: Database, *, app: str | None = None, actor: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    clauses, params = [], []
    if app:
        clauses.append("app = ?")
        params.append(app)
    if actor:
        clauses.append("actor = ?")
        params.append(actor)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.query(f"SELECT * FROM audit_events {where} ORDER BY id DESC LIMIT ?", (*params, limit))
    out = []
    for r in rows:
        item = dict(r)
        for key in ("before", "after", "detail"):
            item[key] = json.loads(item[key]) if item[key] else None
        out.append(item)
    return out
