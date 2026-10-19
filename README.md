# Internal Tools Platform-prototype (Cognition)

A working prototype that answers one question for a fintech client: **could their engineers, working with Devin, build their internal tools themselves instead of on Microsoft Power Apps?**

The client runs three internal apps on Power Apps (a KYC review queue, a refunds dashboard and a feature-flag admin panel) and plans at least ten more. What Power Apps really gives each of those apps is not the screens. It is the governance underneath them:

- who you are and what you may do;
- checks against systems of record;
- approvals;
- connectors to other systems;
- an audit trail;
- a controlled path to production.

This repository builds that governance **once**, as a shared core called **the spine** (`core/`), and puts thin apps on top of it. Two apps run on it today: **Refunds** and **Feature flags**.

> Apps describe their actions and how risky each one is. The spine decides what each risk level requires, runs the checks, collects the signatures, executes once, and records everything.

## How it was built

Devin built it in three sessions, each merged as its own pull request:

| # | Pull request | What it added |
|---|---|---|
| 1 | Spine + Refunds | The whole shared core, the Refunds app, shared pages, tests, CI and docs |
| 2 | Compliance co-signing | A new rule from Compliance: high-risk actions in **any** app also need a compliance signature. A change to the spine only; nothing under `apps/` changed |
| 3 | Feature flags | A second app, built from a one-page spec and a playbook. It inherited approvals, audit, the inbox and the compliance rule without asking for them |

The specs for sessions 2 and 3 are in `docs/specs/`. What each session built, the review feedback and the mistakes caught are in `docs/devin-log.md`.

## What the spine provides

| Capability | Where it lives | Power Apps equivalent |
|---|---|---|
| Identity and roles: demo sign-in, dev API tokens, a Microsoft Entra ID stub | `core/identity/` | Entra ID, Dataverse security roles |
| Permissions and approval rules, in plain YAML | `config/policy.yaml`, `core/policy.py` | Dataverse security roles |
| Checks against systems of record, re-run inside the write transaction | `core/verification.py` | Validation rules and lookups |
| Approvals (details below) | `core/approvals.py` | Power Automate approvals |
| Typed connectors: read-only ledger, payment processor mock, feature-flag service mock | `core/connectors/` | Power Platform connectors |
| Append-only audit log, enforced by database triggers | `core/audit.py`, `core/db.py` | Dataverse auditing |
| App registry, plus a public Platform page that shows all of the above | `core/registry.py`, `core/routes.py` | The Power Apps admin view |
| Tests, a guard test, CI and written conventions | `tests/`, `.github/workflows/`, `AGENTS.md` | Environments and pipelines |

**What the approvals engine enforces:**
- signer types, collected as ordered signatures;
- nobody signs their own request;
- each step needs a different person;
- execution happens exactly once;
- idempotency keys;
- self-serve limits, so a big refund can't be split into small ones that skip a manager.

## The two apps

**Refunds** (`apps/refunds/`, teal). An analyst enters a transaction, the customer's email, an amount and a reason. The spine checks the request against the ledger before anything moves:

1. The transaction exists in the ledger.
2. The original payment has settled (not pending, not disputed).
3. The customer matches.
4. It's within the 90-day refund window.
5. The amount is still refundable, counting refunds already paid and requests still open.

Small refunds pay immediately. Larger ones wait for signatures, then pay out exactly once through the payment processor connector.

**Feature flags** (`apps/flags/`, purple). Engineers turn features on per environment. Changes in the test environment apply at once. Changes for real customers need the engineering lead. Turning a flag fully on (100%) for real customers also needs compliance. A second change to the same flag and environment is refused while one is pending.

## Approval rules

Apps only say how risky an action is. `config/policy.yaml` says what each risk level needs:

| Risk | Needs | Refunds | Feature flags |
|---|---|---|---|
| low | Nothing; executes immediately (still audited) | Up to $500, within the self-serve limits | Any change in the test environment |
| elevated | The app's approver | Above $500, or a small refund that would go over a self-serve limit | Any change for real customers |
| high | The app's approver, then compliance | Above $1,500 | Turning a flag on at 100% for real customers |

**Self-serve limits** (`config/settings.yaml`):
- Refunds paid without a signature can total at most $500 per payment, and $1,000 per person in 24 hours.
- Going over doesn't block the request; it raises it to elevated, so it waits for a manager.

A request appears in someone's inbox only when it's their step. Compliance can co-sign requests from apps they can't open.

## Demo people

| Department | Person | Role | Can |
|---|---|---|---|
| Operations | Amy Clark | Operations analyst | Request refunds |
| Operations | Mark Evans | Operations manager | Request and approve refunds; read the audit log |
| Engineering | Paul Reed | Software engineer | Change feature flags |
| Engineering | Kate Hall | Engineering lead | Change and approve production flag changes; read the audit log |
| Compliance | Sue Turner | Compliance officer | Co-sign high-risk actions in any app; read the audit log |

All people, customers and transactions are fictional. They exist only in `seed/*.yaml`.

## How to run it

**You need** Python 3.11 or newer, and `make`. The first `make` command creates a virtual environment in `.venv` and installs `requirements.txt`. No database server is needed: the app uses two SQLite files in `data/`.

```bash
git clone https://github.com/adgodoyo/Cognition-HA.git
cd Cognition-HA
make demo
```

Then open **http://localhost:8000**. `make demo` resets the demo data from `seed/` and starts the server, so every run starts from the same state.

| Command | What it does |
|---|---|
| `make demo` | Reset the demo data, then serve on http://localhost:8000 in demo mode |
| `make dev` | Serve with auto-reload, without resetting the data |
| `make test` | Run the test suite (88 tests) |
| `make reset` | Rebuild `data/platform.db` and `data/ledger.db` from `seed/` |
| `make -s token user=amy` | Print a dev API token for that person (demo mode only) |

**Without `make`:**

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app_main.py reset
DEMO_MODE=1 .venv/bin/uvicorn app_main:create_app --factory --port 8000
```

**Two browser windows help.** Sign-in is a cookie, so use a normal window for one person and a private window for another. Pages refresh by themselves every 2 seconds, so an action in one window shows up in the other.

**To start over:** click **Reset demo data** on the Platform page, or run `make reset`. A reset signs everyone out and generates new dev tokens.

## A five-minute tour

The full click-by-click version, with every expected result, is in `docs/demo-walkthrough.md`.

1. **Platform** (no sign-in needed). See the spine's capabilities, which apps use them, the permissions matrix, the approval rules per risk level, the connectors, and how little code each app needed.
2. **A bad refund is caught.** As Amy, open Refunds and check `TX-1006`, `luke.ross@example.com`, `100`. "Original payment has settled" fails (the payment is disputed), and Submit stays disabled.
3. **A refund waits for a manager.** Check `TX-1004`, `john.webb@example.com`, `1200`. All five checks pass and the risk is elevated. Submit: it waits for a manager. Amy can't sign her own request, in the UI or through the API (`403 self_approval_forbidden`).
4. **The manager signs.** As Mark, open the Inbox and sign. The refund pays once, and the header shows **Payouts: 1**. Signing again returns `409 already_decided`, and nothing is paid twice.
5. **High risk needs compliance.** As Amy, request `1800` on `TX-1005` (`emma.ford@example.com`). Mark signs (1 of 2). Then Sue, who has no access to Refunds, finds it in her inbox, signs, and it pays.
6. **The second app.** As Paul, turn *Instant payouts* on at 100% in the test environment: applied. Do the same for real customers: "Sent for approval: engineering lead, then compliance". Kate signs, and the request moves on to Sue.
7. **One inbox, one audit log.** As Sue, the refund (teal) and the flag rollout (purple) wait side by side. The Audit log shows both apps in one list, including refused attempts in red.

The same flow works with curl:

```bash
T=$(make -s token user=amy); M=$(make -s token user=mark)
curl -s -X POST localhost:8000/api/refunds -H "Authorization: Bearer $T" -H 'Idempotency-Key: demo-1' \
  -H 'Content-Type: application/json' \
  -d '{"transaction_id":"TX-1004","customer_email":"john.webb@example.com","amount_cents":120000,"reason":"Order cancelled"}'
curl -s -X POST localhost:8000/api/approvals/1/sign -H "Authorization: Bearer $T"   # 403 self_approval_forbidden
curl -s -X POST localhost:8000/api/approvals/1/sign -H "Authorization: Bearer $M"   # executed
curl -s -X POST localhost:8000/api/approvals/1/sign -H "Authorization: Bearer $M"   # 409 already_decided
```

## API

Every endpoint accepts a session cookie or `Authorization: Bearer <token>`. Errors are JSON: `{"error": code, "message": text}`. Interactive docs are at http://localhost:8000/docs.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/me` | Who the server thinks you are |
| POST | `/api/refunds/preview` | Runs the checks and computes the risk; writes nothing |
| POST | `/api/refunds` | Requires an `Idempotency-Key` header |
| GET | `/api/flags` | Every flag's state per environment, with any pending change |
| POST | `/api/flags/changes` | `{flag, environment, enabled, rollout_percent}`; requires an `Idempotency-Key` header |
| POST | `/api/approvals/{id}/sign` | 403 `self_approval_forbidden` / `forbidden` / `not_your_step`; 409 `already_signed` / `already_decided` |
| POST | `/api/approvals/{id}/reject` | Requires a reason |

Every refusal is written to the audit log with outcome `denied`.

## Engineering rules

These come from `AGENTS.md`. They are the conventions every app on the platform follows.

- **No demo records in code.** IDs, names and emails live only in `seed/`. `tests/test_no_demo_literals.py` fails the build if any appears in `core/`, `apps/` or `templates/`.
- **Rules live in config.** Thresholds, the refund window, self-serve limits, roles and approval requirements are in `config/`. Code reads them.
- **Demo mode changes nothing that matters.** `DEMO_MODE=1` enables only the sign-in chooser, dev tokens and the reset endpoint. Checks, approvals, payments, flag changes and audit behave the same with it off.
- **Mocks behave like real systems.** They persist state, honour idempotency keys and can fail.
- **The server decides.** Templates only render what the core returns.
- **Every app ships negative tests:** wrong role, self-approval, double execution, each failing check.

**Two databases model the boundary between the platform and outside systems:**
- `data/platform.db` is what the platform owns: users, approvals, signatures and the audit log.
- `data/ledger.db` stands in for external systems: the ledger, payouts and the flag service. The platform reads the ledger read-only; only the payment processor mock writes settlements to it.

## Adding an app

Follow `playbooks/new-internal-app.md`. An app is:
- a new folder under `apps/`;
- one line in `config/settings.yaml`;
- its roles in `config/policy.yaml`;
- if it talks to a new external system, a new connector file in `core/connectors/`.

Existing core files and existing apps shouldn't need to change. Feature flags was built this way.

## Repository layout

```
core/            the spine: identity, policy, verification, approvals, audit, connectors, registry, shared pages
apps/refunds/    manifest.py, service.py, checks.py, routes.py
apps/flags/      same shape; brings its own connector (core/connectors/flags_mock.py)
templates/       shared pages, plus templates/refunds/ and templates/flags/
config/          settings.yaml (installed apps, thresholds), policy.yaml (permissions, roles, risk -> signers)
seed/            demo people, mock ledger and flags: the only place demo records live
tests/           pytest; tests/fixtures/ holds test-only data
playbooks/       new-internal-app.md: how to add the next app
docs/            demo-walkthrough.md, devin-log.md, specs/
```

## Mocked and out of scope

- **Single sign-on.** Sign-in is a demo chooser. In production it would be Microsoft Entra ID over OIDC; `core/identity/entra_oidc.py` shows where it plugs in.
- **The ledger, payment processor and flag service** are mocks behind the same typed interfaces a real integration would implement.
- **A general workflow engine.** Approvals are ordered signatures, not arbitrary workflows.
- **Production hosting.** This is a single process with SQLite files.
- **Real personal data.** Everything in `seed/` is fictional.
