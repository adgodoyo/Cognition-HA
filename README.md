# Internal Tools Platform (prototype)

Can engineers, working with Devin, replace Power Apps for internal tools? This prototype tests that idea. The hard part of Power Apps isn't the screens. It's the governance underneath them. This repo builds that governance once as a shared **spine** (`core/`), and each app plugs into it.

Every app declares three things: its **actions**, the **checks** each action needs, and the **risk** of each action. The spine handles the rest for all apps:

| Concern | Where |
|---|---|
| Identity and roles (demo sign-in, dev tokens, Entra ID stub) | `core/identity/` |
| Permissions and approval rules (YAML) | `config/policy.yaml`, `core/policy.py` |
| Checks against systems of record, run again inside the write transaction | `core/verification.py` |
| Approvals: signer types, ordered signatures, no self-approval, execute once, idempotency, self-serve limits (no splitting big actions into small ones) | `core/approvals.py` |
| Typed connectors (read-only ledger, payment processor mock, feature flag service mock) | `core/connectors/` |
| Append-only audit log (enforced by database triggers) | `core/audit.py`, `core/db.py` |
| App registry and the Platform page | `core/registry.py` |

Two apps run on it today:
- **Refunds** (`apps/refunds/`): check a refund against the ledger, collect sign-off by amount, pay out exactly once.
- **Feature flags** (`apps/flags/`): turn features on per environment. Test changes apply at once. Production changes need the engineering lead, and turning a flag fully on for real customers also needs compliance. It was added without changing any existing `core/` file: the approvals, audit, inbox and compliance rule all came from the spine.

## Run it
Needs Python 3.11 or newer. The Makefile creates `.venv` automatically.

```bash
make demo     # reset demo data from seed/ and serve on http://localhost:8000 (DEMO_MODE=1)
make test     # pytest
make reset    # rebuild data/platform.db and data/ledger.db from seed/
make -s token user=amy   # print a dev API token (DEMO_MODE only)
```

For the guided tour, see [docs/demo-walkthrough.md](docs/demo-walkthrough.md).

## Layout
```
core/            the spine: identity, policy, verification, approvals, audit, connectors, registry, shared pages
apps/refunds/    manifest.py, service.py, checks.py, routes.py
apps/flags/      same shape; brings its own connector (core/connectors/flags_mock.py)
templates/       shared pages + templates/refunds/, templates/flags/
config/          settings.yaml (installed apps, thresholds), policy.yaml (permissions, roles, risk → signers)
seed/            demo people, mock ledger and flags: the ONLY place demo records live
tests/           pytest; tests/fixtures/ holds test-only data
playbooks/       new-internal-app.md: how Devin adds the next app
```

**Two databases model the boundary between our systems and outside ones:**
- `data/platform.db` holds what the platform owns: users, approvals, signatures, audit.
- `data/ledger.db` stands in for external systems: the ledger, payouts and the feature flag service. The platform reads the ledger **read-only**. Only the payment processor mock writes settlements, and only the flag service mock writes flag state.

## API
All endpoints take `Authorization: Bearer <token>` or the session cookie. Errors are JSON in the form `{"error": code, "message": text}`.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/me` | current principal |
| POST | `/api/refunds/preview` | runs the checks and computes risk. Writes nothing |
| POST | `/api/refunds` | requires the `Idempotency-Key` header |
| GET | `/api/flags` | every flag's state per environment, with any pending change |
| POST | `/api/flags/changes` | `{flag, environment, enabled, rollout_percent}`; requires the `Idempotency-Key` header |
| POST | `/api/approvals/{id}/sign` | 403 `self_approval_forbidden` / `forbidden`, 409 `already_signed` / `already_decided` |
| POST | `/api/approvals/{id}/reject` | requires a reason |

## Demo mode
`DEMO_MODE=1` turns on only three things: the identity chooser on the sign-in page, dev API tokens, and the reset endpoint. Checks, approvals, payments, flag changes and audit work exactly the same with it off.

## Adding an app
Follow [playbooks/new-internal-app.md](playbooks/new-internal-app.md) and the conventions in [AGENTS.md](AGENTS.md). An app is a new folder plus one line in `config/settings.yaml` and its roles in `config/policy.yaml`. You shouldn't need to edit `core/` or the existing apps.
