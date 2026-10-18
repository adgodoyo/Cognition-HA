"""Demo identity provider: a sign-in chooser plus a session cookie, and dev API tokens
for curl. The chooser and tokens only work in DEMO_MODE."""
from __future__ import annotations

from starlette.requests import Request

from core.db import Database
from core.errors import Forbidden, InvalidToken
from core.identity.base import Principal, principal_from_row

SESSION_USER = "username"
SESSION_EPOCH = "epoch"


class MockIdentityProvider:
    def __init__(self, db: Database, demo_mode: bool):
        self.db = db
        self.demo_mode = demo_mode

    def _lookup(self, username: str) -> Principal | None:
        row = self.db.query_one("SELECT * FROM users WHERE username = ?", (username,))
        return principal_from_row(row) if row else None

    def current_principal(self, request: Request) -> Principal | None:
        auth = request.headers.get("authorization")
        if auth:
            return self._from_token(auth)
        username = request.session.get(SESSION_USER)
        if not username:
            return None
        if request.session.get(SESSION_EPOCH) != self.db.meta("session_epoch"):
            request.session.clear()  # the demo data was reset since this sign-in
            return None
        return self._lookup(username)

    def _from_token(self, header: str) -> Principal:
        if not self.demo_mode:
            raise InvalidToken("Dev API tokens only work when DEMO_MODE is on. Sign in through single sign-on instead.")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise InvalidToken("Send the token as 'Authorization: Bearer <token>'. Get one with: make -s token user=<username>")
        row = self.db.query_one("SELECT * FROM users WHERE dev_token = ?", (token.strip(),))
        if not row:
            raise InvalidToken(
                "That token is not valid (tokens change on every reset). Get a fresh one with: make -s token user=<username>"
            )
        return principal_from_row(row)

    # Sign-in chooser (DEMO_MODE only)

    def people(self) -> list[Principal]:
        rows = self.db.query("SELECT * FROM users ORDER BY department, name")
        return [principal_from_row(r) for r in rows]

    def sign_in(self, request: Request, username: str) -> Principal:
        if not self.demo_mode:
            raise Forbidden("The demo sign-in chooser is only available in DEMO_MODE.")
        principal = self._lookup(username)
        if principal is None:
            raise Forbidden("Unknown person.")
        request.session.clear()
        request.session[SESSION_USER] = principal.username
        request.session[SESSION_EPOCH] = self.db.meta("session_epoch")
        return principal

    def sign_out(self, request: Request) -> None:
        request.session.clear()

    def dev_token(self, username: str) -> str | None:
        row = self.db.query_one("SELECT dev_token FROM users WHERE username = ?", (username,))
        return row["dev_token"] if row else None
