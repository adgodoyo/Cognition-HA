"""App factory: settings, the spine, installed apps, middleware and routes.

    uvicorn app_main:create_app --factory     # serve
    python app_main.py reset                  # rebuild both databases from seed/
    python app_main.py token <username>       # print a dev API token
"""
from __future__ import annotations

import sys

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from core import web
from core.approvals import validate_signer_types
from core.connectors.ledger_mock import LedgerMock
from core.connectors.payments_mock import PaymentsMock
from core.context import PlatformContext
from core.db import Database, reset_all
from core.identity.mock_provider import MockIdentityProvider
from core.policy import Policy
from core.registry import count_lines, load_apps, validate
from core.routes import router as core_router
from core.settings import Settings, load_settings


def build_platform(settings: Settings) -> PlatformContext:
    policy = Policy(settings.policy)
    validate_signer_types(policy)
    db = Database(settings.platform_db)
    if settings.identity_provider != "mock":
        raise ValueError("Only the mock identity provider is wired up; see core/identity/entra_oidc.py.")
    identity = MockIdentityProvider(db, settings.demo_mode)

    ledger = LedgerMock(settings.ledger_db, settings.seed_dir)
    payments = PaymentsMock(settings.ledger_db, settings.seed_dir, ledger)
    platform = PlatformContext(settings=settings, policy=policy, db=db, identity=identity,
                               connectors={ledger.name: ledger, payments.name: payments})

    for manifest in load_apps(settings):
        platform.apps[manifest.name] = manifest
        for name, connector in manifest.connectors.items():
            if name in platform.connectors:
                raise ValueError(f"App {manifest.name!r} brings connector {name!r}, which already exists.")
            platform.connectors[name] = connector
    validate(platform)

    if not db.exists():
        reset_all(settings, policy, platform.connectors)
    else:
        db.init_schema()
        for connector in platform.connectors.values():
            connector.ensure_ready()
    platform.loc_stats = count_lines(settings.root, list(platform.apps))
    return platform


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    platform = build_platform(settings)

    app = FastAPI(
        title=f"{settings.platform_name} API",
        description="Every app's actions go through the same spine: identity, verification, approvals, connectors, audit.",
    )
    app.state.platform = platform
    web.install(app)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax")
    app.include_router(core_router)
    for manifest in platform.apps.values():
        app.include_router(manifest.router)
    return app


def main(argv: list[str]) -> int:
    settings = load_settings()
    if argv[:1] == ["reset"]:
        platform = build_platform(settings)
        reset_all(settings, platform.policy, platform.connectors)
        print(f"Reset {settings.platform_db} and {settings.ledger_db} from {settings.seed_dir}/")
        return 0
    if argv[:1] == ["token"] and len(argv) == 2:
        platform = build_platform(settings)
        token = platform.identity.dev_token(argv[1])
        if not token:
            print(f"No user named {argv[1]!r}.", file=sys.stderr)
            return 1
        print(token)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
