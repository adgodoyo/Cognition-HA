"""Policy: permissions, roles and what each risk level requires, read from config/policy.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.errors import Forbidden
from core.identity.base import Principal

RISK_LEVELS = ("low", "elevated", "high")


@dataclass(frozen=True)
class Role:
    key: str
    label: str
    permissions: tuple[str, ...]


class Policy:
    def __init__(self, raw: dict[str, Any]):
        self.permissions: dict[str, str] = dict(raw.get("permissions", {}))
        self.roles: dict[str, Role] = {
            key: Role(key, spec.get("label", key), tuple(spec.get("permissions", [])))
            for key, spec in (raw.get("roles") or {}).items()
        }
        self.approval_requirements: dict[str, list[str]] = {
            level: list(steps or []) for level, steps in (raw.get("approval_requirements") or {}).items()
        }
        self.app_names: frozenset[str] = frozenset()
        self._validate()

    def bind_apps(self, names) -> None:
        """Lets permission_groups tell app permissions from platform-wide ones."""
        self.app_names = frozenset(names)

    def _validate(self) -> None:
        for role in self.roles.values():
            unknown = [p for p in role.permissions if p not in self.permissions]
            if unknown:
                raise ValueError(f"policy.yaml: role {role.key!r} grants unknown permissions {unknown}.")
        missing = [level for level in RISK_LEVELS if level not in self.approval_requirements]
        if missing:
            raise ValueError(f"policy.yaml: approval_requirements is missing risk levels {missing}.")
        for level, steps in self.approval_requirements.items():
            if len(set(steps)) != len(steps):
                raise ValueError(f"policy.yaml: risk level {level!r} lists the same signer type twice.")

    # Questions the rest of the platform asks

    def has(self, principal: Principal | None, permission: str) -> bool:
        if principal is None:
            return False
        role = self.roles.get(principal.role)
        return bool(role and permission in role.permissions)

    def require(self, principal: Principal, permission: str, *, app: str | None = None, action: str | None = None) -> None:
        if not self.has(principal, permission):
            label = self.permissions.get(permission, permission)
            raise Forbidden(
                f"Your role doesn't allow this ({label.lower()}).", app=app, action=action or permission
            )

    def can_open(self, principal: Principal | None, app: str) -> bool:
        return any(self.has(principal, p) for p in self.permissions_for_app(app))

    def permissions_for_app(self, app: str) -> list[str]:
        return [p for p in self.permissions if p.split(".", 1)[0] == app]

    def role_label(self, role: str) -> str:
        return self.roles[role].label if role in self.roles else role

    def can_cannot(self, role: str) -> tuple[list[str], list[str]]:
        granted = set(self.roles[role].permissions) if role in self.roles else set()
        can = [label for p, label in self.permissions.items() if p in granted]
        cannot = [label for p, label in self.permissions.items() if p not in granted]
        return can, cannot

    def requirements_for(self, risk: str) -> list[str]:
        if risk not in self.approval_requirements:
            raise ValueError(f"Unknown risk level {risk!r}.")
        return list(self.approval_requirements[risk])

    def permission_groups(self) -> list[tuple[str, list[str]]]:
        """Permissions grouped by app, in declaration order. Prefixes that aren't apps
        (audit, compliance, ...) share one "platform" group."""
        groups: dict[str, list[str]] = {}
        for permission in self.permissions:
            prefix = permission.split(".", 1)[0]
            if self.app_names and prefix not in self.app_names:
                prefix = "platform"
            groups.setdefault(prefix, []).append(permission)
        return list(groups.items())
