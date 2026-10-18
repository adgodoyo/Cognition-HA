"""The error contract. Every refusal is a PlatformError; core/web.py turns it into JSON
for the API or a readable page for the UI, and audits it with outcome "denied"."""
from __future__ import annotations

from typing import Any


class PlatformError(Exception):
    status = 400
    code = "error"
    default_message = "The request was refused."

    def __init__(
        self,
        message: str | None = None,
        *,
        app: str | None = None,
        action: str | None = None,
        entity: str | None = None,
        extra: dict[str, Any] | None = None,
    ):
        self.message = message or self.default_message
        self.app = app
        self.action = action
        self.entity = entity
        self.extra = extra or {}
        super().__init__(self.message)

    def to_json(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.extra}


class Unauthenticated(PlatformError):
    status, code = 401, "unauthenticated"
    default_message = "You are not signed in."


class InvalidToken(PlatformError):
    status, code = 401, "invalid_token"
    default_message = "That API token is not valid."


class Forbidden(PlatformError):
    status, code = 403, "forbidden"
    default_message = "You don't have permission to do that."


class SelfApprovalForbidden(PlatformError):
    status, code = 403, "self_approval_forbidden"
    default_message = "You can't sign your own request."


class AlreadySigned(PlatformError):
    status, code = 403, "already_signed"
    default_message = "You already signed this request."


class NotYourStep(PlatformError):
    status, code = 403, "not_your_step"
    default_message = "The next signature on this request is not yours to give."


class AlreadyDecided(PlatformError):
    status, code = 409, "already_decided"
    default_message = "This request has already been decided."


class IdempotencyKeyRequired(PlatformError):
    status, code = 400, "idempotency_key_required"
    default_message = "Send an Idempotency-Key header so a retried request can't be created twice."


class IdempotencyKeyConflict(PlatformError):
    status, code = 409, "idempotency_key_conflict"
    default_message = "This Idempotency-Key was already used for a different request."


class ChecksFailed(PlatformError):
    status, code = 422, "checks_failed"
    default_message = "The request didn't pass verification against the systems of record."


class ReasonRequired(PlatformError):
    status, code = 422, "reason_required"
    default_message = "Give a reason for rejecting."


class InvalidInput(PlatformError):
    status, code = 422, "invalid_input"
    default_message = "Some of the input is not valid."


class NotFound(PlatformError):
    status, code = 404, "not_found"
    default_message = "No such request."
