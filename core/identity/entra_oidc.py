"""Where Microsoft Entra ID plugs in (stub, not wired up in this prototype).

In production, sign-in is Entra ID single sign-on over OpenID Connect:

1. /signin redirects to https://login.microsoftonline.com/<tenant>/oauth2/v2.0/authorize
   with the app's client ID, scope "openid profile email" and a nonce.
2. The callback exchanges the code for an ID token and validates it (signature against the
   tenant's JWKS, issuer, audience = client ID, expiry, nonce). Use a maintained library
   such as msal or authlib for this; don't hand-roll JWT validation.
3. The validated claims map to the same Principal the rest of the code already uses:

       Principal(
           username   = claims["preferred_username"],   # or "oid" for a stable ID
           name       = claims["name"],
           title      = claims.get("jobTitle", ""),     # via Microsoft Graph if not in the token
           department = claims.get("department", ""),
           role       = <app role from claims["roles"], mapped to a policy.yaml role>,
       )

   Roles are assigned to people or groups in Entra ID as app roles, so access is managed
   in the directory, not in this app. Nothing outside core/identity/ changes.
4. The username is stored in the session cookie exactly as MockIdentityProvider does.
"""
from __future__ import annotations

from starlette.requests import Request

from core.identity.base import Principal


class EntraOIDCProvider:
    def __init__(self, tenant_id: str, client_id: str, role_map: dict[str, str]):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.role_map = role_map

    def principal_from_claims(self, claims: dict) -> Principal:
        app_roles = claims.get("roles", [])
        role = next((self.role_map[r] for r in app_roles if r in self.role_map), "")
        return Principal(
            username=claims["preferred_username"],
            name=claims.get("name", claims["preferred_username"]),
            title=claims.get("jobTitle", ""),
            department=claims.get("department", ""),
            role=role,
        )

    def current_principal(self, request: Request) -> Principal | None:
        raise NotImplementedError("Entra ID sign-in is not configured in this prototype; see the module docstring.")
