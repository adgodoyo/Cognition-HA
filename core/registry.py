"""Registry: installed apps. Each app's manifest.py exposes build(settings) -> AppManifest."""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter

from core.approvals import ActionSpec


@dataclass
class AppManifest:
    name: str
    title: str
    color: str
    description: str
    permissions: list[str]
    actions: list[ActionSpec]
    router: APIRouter
    nav_path: str
    connectors_used: list[str]
    # Connectors the app brings itself (kept in data/ledger.db, seeded from seed/<name>.yaml).
    connectors: dict[str, Any] = field(default_factory=dict)


def load_apps(settings) -> list[AppManifest]:
    manifests = []
    for name in settings.installed_apps:
        module = importlib.import_module(f"apps.{name}.manifest")
        manifest = module.build(settings)
        if manifest.name != name:
            raise ValueError(f"apps/{name}/manifest.py builds an app named {manifest.name!r}.")
        manifests.append(manifest)
    return manifests


def validate(platform) -> None:
    """Fail fast on configuration that doesn't line up."""
    policy = platform.policy
    for m in platform.apps.values():
        for permission in m.permissions:
            if permission not in policy.permissions:
                raise ValueError(f"App {m.name!r} declares permission {permission!r}, which policy.yaml doesn't define.")
        for spec in m.actions:
            if spec.request_permission not in policy.permissions:
                raise ValueError(f"Action {m.name}.{spec.name} needs unknown permission {spec.request_permission!r}.")
        for c in m.connectors_used:
            if c not in platform.connectors:
                raise ValueError(f"App {m.name!r} uses unknown connector {c!r}.")


# What the Platform page shows: each capability, where it lives, and which apps use it.

@dataclass(frozen=True)
class Capability:
    name: str
    implemented_in: str
    used_by: Callable[[AppManifest], bool]


CAPABILITIES = [
    Capability("Identity and roles", "core/identity/, core/policy.py", lambda m: True),
    Capability("Verification against systems of record", "core/verification.py", lambda m: any(a.checks for a in m.actions)),
    Capability("Approvals", "core/approvals.py", lambda m: bool(m.actions)),
    Capability("Connectors", "core/connectors/", lambda m: bool(m.connectors_used)),
    Capability("Audit trail", "core/audit.py", lambda m: bool(m.actions)),
    Capability("Governed path to production", ".github/workflows/ci.yml, AGENTS.md, tests/", lambda m: True),
]


def _count(path: Path) -> int:
    files = [path] if path.is_file() else sorted(path.rglob("*.py"))
    total = 0
    for f in files:
        for line in f.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                total += 1
    return total


def count_lines(root: Path, app_names: list[str]) -> list[dict[str, Any]]:
    """Lines of code (non-blank, non-comment Python) per core module and per app."""
    rows = []
    core = root / "core"
    for entry in sorted(core.iterdir()):
        if entry.name.startswith("_") or entry.name == "__pycache__":
            continue
        if entry.is_dir() or entry.suffix == ".py":
            rows.append({"group": "core", "module": f"core/{entry.name}{'/' if entry.is_dir() else ''}", "lines": _count(entry)})
    for name in app_names:
        rows.append({"group": name, "module": f"apps/{name}/", "lines": _count(root / "apps" / name)})
    return rows
