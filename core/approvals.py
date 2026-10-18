"""Approvals: apps declare actions and their risk; the spine decides what each risk level
requires, collects signatures in order, executes once and records everything."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from core import audit
from core.db import utcnow_iso
from core.errors import (
    AlreadyDecided,
    AlreadySigned,
    ChecksFailed,
    Forbidden,
    IdempotencyKeyConflict,
    IdempotencyKeyRequired,
    NotFound,
    NotYourStep,
    PlatformError,
    ReasonRequired,
    SelfApprovalForbidden,
)
from core.identity.base import Principal
from core.verification import Check, Ctx, build_ctx, run_checks


@dataclass
class ActionSpec:
    app: str
    name: str
    request_permission: str
    checks: list[Check]
    risk_level: Callable[[dict], str]            # "low" | "elevated" | "high", from the app's config
    execute: Callable[[dict, str, Ctx], dict]    # (payload, idempotency_key, ctx) -> result
    describe: Callable[[dict], str]              # one line for the inbox


# Signer types: who qualifies for a step, and the short label used in progress text.
# A new kind of signer is a new entry here plus a line in policy.yaml; apps don't change.

@dataclass(frozen=True)
class SignerType:
    key: str
    qualifies: Callable[[Any, Principal, str], bool]  # (platform, principal, app)
    label: Callable[[Any, str], str]                  # (platform, app)


SIGNER_TYPES: dict[str, SignerType] = {}


def register_signer_type(signer: SignerType) -> None:
    SIGNER_TYPES[signer.key] = signer


register_signer_type(
    SignerType(
        key="app_approver",
        qualifies=lambda platform, who, app: platform.policy.has(who, f"{app}.approve"),
        label=lambda platform, app: platform.settings.app_settings(app).get("approver_label", "approver"),
    )
)


def validate_signer_types(policy) -> None:
    """Fail fast at startup if policy.yaml names a signer type that doesn't exist."""
    for level, steps in policy.approval_requirements.items():
        unknown = [s for s in steps if s not in SIGNER_TYPES]
        if unknown:
            raise ValueError(
                f"policy.yaml: risk level {level!r} requires unknown signer types {unknown}. "
                f"Known: {sorted(SIGNER_TYPES)}."
            )


# Reading approvals

@dataclass
class Signature:
    requirement: str
    signer: str
    role: str
    signed_at: str


@dataclass
class Approval:
    id: int
    app: str
    action: str
    payload: dict[str, Any]
    description: str
    risk: str
    requirements: list[str]
    status: str
    requester: str
    idempotency_key: str
    request_hash: str
    result: dict[str, Any] | None
    error: str | None
    reject_reason: str | None
    rejected_by: str | None
    created_at: str
    updated_at: str
    signatures: list[Signature] = field(default_factory=list)

    @property
    def next_requirement(self) -> str | None:
        signed = {s.requirement for s in self.signatures}
        return next((r for r in self.requirements if r not in signed), None)

    def signed_by(self, username: str) -> bool:
        return any(s.signer == username for s in self.signatures)

    @property
    def entity(self) -> str:
        return f"request #{self.id}"


def _from_row(row: sqlite3.Row, signatures: list[Signature]) -> Approval:
    return Approval(
        id=row["id"],
        app=row["app"],
        action=row["action"],
        payload=json.loads(row["payload"]),
        description=row["description"],
        risk=row["risk"],
        requirements=json.loads(row["requirements"]),
        status=row["status"],
        requester=row["requester"],
        idempotency_key=row["idempotency_key"],
        request_hash=row["request_hash"],
        result=json.loads(row["result"]) if row["result"] else None,
        error=row["error"],
        reject_reason=row["reject_reason"],
        rejected_by=row["rejected_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        signatures=signatures,
    )


def _signatures(conn: sqlite3.Connection, ids: list[int]) -> dict[int, list[Signature]]:
    out: dict[int, list[Signature]] = {i: [] for i in ids}
    if not ids:
        return out
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM approval_signatures WHERE approval_id IN ({marks}) ORDER BY id", ids
    ).fetchall()
    for r in rows:
        out[r["approval_id"]].append(Signature(r["requirement"], r["signer"], r["role"], r["signed_at"]))
    return out


def _load(conn: sqlite3.Connection, where: str, params: tuple) -> list[Approval]:
    rows = conn.execute(f"SELECT * FROM approvals {where}", params).fetchall()
    sigs = _signatures(conn, [r["id"] for r in rows])
    return [_from_row(r, sigs[r["id"]]) for r in rows]


def get(platform, approval_id: int) -> Approval | None:
    with platform.db.read() as conn:
        found = _load(conn, "WHERE id = ?", (approval_id,))
    return found[0] if found else None


def list_approvals(platform, *, app: str | None = None, requester: str | None = None,
                   statuses: tuple[str, ...] | None = None) -> list[Approval]:
    clauses, params = [], []
    if app:
        clauses.append("app = ?")
        params.append(app)
    if requester:
        clauses.append("requester = ?")
        params.append(requester)
    if statuses:
        clauses.append(f"status IN ({','.join('?' * len(statuses))})")
        params.extend(statuses)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with platform.db.read() as conn:
        return _load(conn, f"{where} ORDER BY id DESC", tuple(params))


# Text shown to people

def signer_label(platform, app: str, key: str) -> str:
    return SIGNER_TYPES[key].label(platform, app)


def needs_text(platform, app: str, requirements: list[str]) -> str:
    if not requirements:
        return "executes immediately"
    return "needs " + ", then ".join(signer_label(platform, app, r) for r in requirements)


def progress_text(platform, a: Approval) -> str:
    if not a.requirements:
        return "No approval needed"
    signed = {s.requirement for s in a.signatures}
    parts = [signer_label(platform, a.app, r) + (" ✓" if r in signed else "") for r in a.requirements]
    return f"{len(signed)} of {len(a.requirements)}: {', '.join(parts)}"


def status_text(platform, a: Approval) -> str:
    if a.status == "pending":
        return f"Waiting for {signer_label(platform, a.app, a.next_requirement)} approval"
    return {
        "approved": "Approved, executing",
        "executed": "Executed",
        "failed": "Failed",
        "rejected": "Rejected",
    }.get(a.status, a.status)


# Who may sign

def _sign_refusal(platform, principal: Principal, a: Approval) -> PlatformError | None:
    ctx = {"app": a.app, "action": f"{a.action}.sign", "entity": a.entity}
    if a.status != "pending":
        return AlreadyDecided(f"This request is already {a.status}.", **ctx)
    if principal.username == a.requester:
        return SelfApprovalForbidden(**ctx)
    if a.signed_by(principal.username):
        return AlreadySigned(**ctx)
    step = a.next_requirement
    if SIGNER_TYPES[step].qualifies(platform, principal, a.app):
        return None
    if not any(SIGNER_TYPES[r].qualifies(platform, principal, a.app) for r in a.requirements):
        return Forbidden(f"Your role can't approve {a.app} requests.", **ctx)
    return NotYourStep(f"The next step needs {signer_label(platform, a.app, step)} approval.", **ctx)


def can_sign(platform, principal: Principal | None, a: Approval) -> tuple[bool, str]:
    """What templates use to enable or disable Sign and Reject. The server re-checks on submit."""
    if principal is None:
        return False, "Sign in first."
    refusal = _sign_refusal(platform, principal, a)
    return (True, "") if refusal is None else (False, refusal.message)


def can_sign_anything(platform, principal: Principal | None) -> bool:
    if principal is None:
        return False
    return any(s.qualifies(platform, principal, app) for s in SIGNER_TYPES.values() for app in platform.apps)


def waiting_for(platform, principal: Principal) -> list[Approval]:
    return [a for a in list_approvals(platform, statuses=("pending",)) if can_sign(platform, principal, a)[0]]


# Preview, submit, sign, reject

def _request_hash(app: str, action: str, payload: dict) -> str:
    return hashlib.sha256(json.dumps({"app": app, "action": action, "payload": payload}, sort_keys=True).encode()).hexdigest()


def preview(platform, principal: Principal, app: str, action: str, payload: dict) -> dict[str, Any]:
    """Run the checks and report the risk. Writes nothing."""
    spec = platform.action(app, action)
    platform.policy.require(principal, spec.request_permission, app=app, action=f"{action}.preview")
    with platform.db.read() as conn:
        ctx = build_ctx(platform, app, conn)
    outcomes = run_checks(spec.checks, payload, ctx)
    risk = spec.risk_level(payload)
    requirements = platform.policy.requirements_for(risk)
    return {
        "checks": [o.to_dict() for o in outcomes],
        "all_passed": all(o.passed for o in outcomes),
        "risk": risk,
        "requirements": requirements,
        "needs": needs_text(platform, app, requirements),
    }


def submit(platform, principal: Principal, app: str, action: str, payload: dict,
           idempotency_key: str | None) -> tuple[Approval, bool]:
    """Create a request. Returns (approval, created). The same key returns the existing request."""
    spec = platform.action(app, action)
    platform.policy.require(principal, spec.request_permission, app=app, action=f"{action}.request")
    if not idempotency_key:
        raise IdempotencyKeyRequired(app=app, action=f"{action}.request")
    request_hash = _request_hash(app, action, payload)
    description = spec.describe(payload)

    with platform.db.write() as conn:
        existing = _load(conn, "WHERE idempotency_key = ?", (idempotency_key,))
        if existing:
            a = existing[0]
            if a.request_hash != request_hash or a.requester != principal.username:
                raise IdempotencyKeyConflict(app=app, action=f"{action}.request", entity=a.entity)
            return a, False

        # Re-verify inside the write transaction; never trust a preview.
        ctx = build_ctx(platform, app, conn)
        outcomes = run_checks(spec.checks, payload, ctx)
        failed = [o.to_dict() for o in outcomes if not o.passed]
        if failed:
            raise ChecksFailed(
                app=app, action=f"{action}.request",
                extra={"failed_checks": failed, "description": description, "payload": payload},
            )
        risk = spec.risk_level(payload)
        requirements = platform.policy.requirements_for(risk)
        now = utcnow_iso()
        cur = conn.execute(
            "INSERT INTO approvals (app, action, payload, description, risk, requirements, status, requester,"
            " idempotency_key, request_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (app, action, json.dumps(payload, sort_keys=True), description, risk, json.dumps(requirements),
             "pending" if requirements else "approved", principal.username, idempotency_key, request_hash, now, now),
        )
        approval_id = cur.lastrowid
        detail = {"description": description, "payload": payload, "risk": risk,
                  "needs": needs_text(platform, app, requirements), "checks": [o.to_dict() for o in outcomes]}
        if requirements:
            audit.record(platform.db, actor=principal.username, role=principal.role, app=app,
                         action=f"{action}.request", entity=f"request #{approval_id}", outcome="checked",
                         after={"status": "pending"}, detail=detail, conn=conn)

    if not requirements:
        _execute(platform, approval_id, principal, detail=detail, action_label=f"{action}.request")
    return get(platform, approval_id), True


def _execute(platform, approval_id: int, principal: Principal, *, detail: dict, action_label: str) -> None:
    """Run the action exactly once for an approved request, then record the outcome."""
    a = get(platform, approval_id)
    spec = platform.action(a.app, a.action)
    with platform.db.read() as conn:
        ctx = build_ctx(platform, a.app, conn)
    try:
        result, error, status = spec.execute(a.payload, f"approval:{a.id}", ctx), None, "executed"
    except Exception as exc:  # the connector raised: record the failure, never retry silently
        result, error, status = None, str(exc), "failed"
    with platform.db.write() as conn:
        conn.execute(
            "UPDATE approvals SET status = ?, result = ?, error = ?, updated_at = ? WHERE id = ? AND status = 'approved'",
            (status, json.dumps(result, default=str) if result is not None else None, error, utcnow_iso(), a.id),
        )
        audit.record(platform.db, actor=principal.username, role=principal.role, app=a.app, action=action_label,
                     entity=a.entity, outcome=status, before={"status": "approved"},
                     after={"status": status, "result": result, "error": error}, detail=detail, conn=conn)


def sign(platform, principal: Principal, approval_id: int) -> Approval:
    a = get(platform, approval_id)
    if a is None:
        raise NotFound(entity=f"request #{approval_id}")
    refusal = _sign_refusal(platform, principal, a)
    if refusal:
        raise refusal

    action_label = f"{a.action}.sign"
    with platform.db.write() as conn:
        a = _load(conn, "WHERE id = ?", (approval_id,))[0]
        refusal = _sign_refusal(platform, principal, a)  # re-check under the write lock
        if refusal:
            raise refusal
        step = a.next_requirement
        try:
            conn.execute(
                "INSERT INTO approval_signatures (approval_id, requirement, signer, role, signed_at) VALUES (?, ?, ?, ?, ?)",
                (a.id, step, principal.username, principal.role, utcnow_iso()),
            )
        except sqlite3.IntegrityError:
            raise AlreadyDecided("That step was just signed by someone else.", app=a.app, action=action_label, entity=a.entity)
        before = {"status": "pending", "progress": progress_text(platform, a)}
        a.signatures.append(Signature(step, principal.username, principal.role, utcnow_iso()))
        detail = {"description": a.description, "step": signer_label(platform, a.app, step),
                  "progress": progress_text(platform, a)}
        is_last = a.next_requirement is None
        if is_last:
            cur = conn.execute(
                "UPDATE approvals SET status = 'approved', updated_at = ? WHERE id = ? AND status = 'pending'",
                (utcnow_iso(), a.id),
            )
            if cur.rowcount != 1:
                raise AlreadyDecided(app=a.app, action=action_label, entity=a.entity)
        else:
            conn.execute("UPDATE approvals SET updated_at = ? WHERE id = ?", (utcnow_iso(), a.id))
            audit.record(platform.db, actor=principal.username, role=principal.role, app=a.app, action=action_label,
                         entity=a.entity, outcome="allowed", before=before,
                         after={"status": "pending", "progress": progress_text(platform, a)}, detail=detail, conn=conn)

    if is_last:
        _execute(platform, a.id, principal, detail=detail, action_label=action_label)
    return get(platform, a.id)


def reject(platform, principal: Principal, approval_id: int, reason: str | None) -> Approval:
    a = get(platform, approval_id)
    if a is None:
        raise NotFound(entity=f"request #{approval_id}")
    action_label = f"{a.action}.reject"
    refusal = _sign_refusal(platform, principal, a)
    if refusal:
        refusal.action = action_label
        raise refusal
    reason = (reason or "").strip()
    if not reason:
        raise ReasonRequired(app=a.app, action=action_label, entity=a.entity)
    with platform.db.write() as conn:
        cur = conn.execute(
            "UPDATE approvals SET status = 'rejected', reject_reason = ?, rejected_by = ?, updated_at = ?"
            " WHERE id = ? AND status = 'pending'",
            (reason, principal.username, utcnow_iso(), a.id),
        )
        if cur.rowcount != 1:
            raise AlreadyDecided(app=a.app, action=action_label, entity=a.entity)
        audit.record(platform.db, actor=principal.username, role=principal.role, app=a.app, action=action_label,
                     entity=a.entity, outcome="allowed", before={"status": "pending"},
                     after={"status": "rejected"}, detail={"description": a.description, "reason": reason}, conn=conn)
    return get(platform, a.id)
