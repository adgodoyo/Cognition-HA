# Devin log

One row per session. Wall-clock and ACUs are filled in by the human reviewer.

| # | Phase | Task | Wall-clock | ACUs | Review comments | Mistakes caught |
|---|-------|------|-----------:|-----:|-----------------|-----------------|
| 1 | Spine + Refunds | Build the shared core (identity, policy, verification, approvals, connectors, audit, registry), the Refunds app, shared pages, tests, CI and docs | | | | See entry 1 |

## Entry template

```
### Session N: <phase>
- Task:
- Built:
- Files changed:
- Tests: `make test` → <n passed>
- Walkthrough: <clicked through twice with a reset in between? anything that didn't match?>
- Went wrong / caught:
- Assumptions and open questions:
```

## Session 1: Spine + Refunds
- **Task:** Build the spine and the first app (Refunds) as a prototype that answers "could we build our internal tools ourselves instead of on Power Apps?"
- **Built:**
  - `core/`: identity (demo provider, dev tokens, Entra ID stub), policy, verification, approvals (signer-type registry, ordered signatures, execute-once), audit (append-only, enforced by triggers), connectors (read-only ledger, payment processor mock with idempotency and settlement), registry, shared pages, live updates.
  - `apps/refunds/`: five checks, risk levels from config, UI and API.
- **Files changed:** whole repository (new).
- **Tests:** `make test` → 63 passed.
- **Walkthrough:** `docs/demo-walkthrough.md`, clicked through twice in the browser with a reset in between.
- **Went wrong / caught:**
  - The guard test matches whole words, case-insensitively, so the demo username "mark" doesn't false-positive on words like "markupsafe". That also means the HTML `<mark>` tag can't be used in templates.
  - `pytest` needed `pythonpath = . tests` to import `app_main` and `conftest`.
  - Found during the walkthrough: live refresh re-fetched a refused page every few seconds, writing a new "denied" audit row each time. Background polls now get a 204 and are not audited (regression test added). The Audit log link is now shown greyed out to roles without access, and the refusal is red and names the missing permission.
  - Reviewer feedback: inboxes looked empty because low-risk refunds execute right away and dropped out of both inboxes. Inboxes now show recent requests and recent decisions.
  - Reviewer feedback: small self-approved refunds could be chained to skip the manager. Added `SelfServeLimit` in `core/approvals.py` (running totals per payment and per person per 24h, from config). Going over escalates the risk instead of blocking.
- **Assumptions:** see the pull request description.

## Session 2: Compliance co-signing (spine change)
- **Task:** "High-risk actions in any internal app must also be co-signed by Compliance." Spec saved as `docs/specs/compliance-cosign.md`. Scope: `core/`, `config/`, `seed/`, `tests/`; nothing under `apps/`.
- **Built:**
  - `compliance_cosigner` signer type in `core/approvals.py` (holds `compliance.cosign`, any app, label "compliance"). `high: [app_approver, compliance_cosigner]` in `config/policy.yaml`, plus the permission and `compliance_officer` role. Seed user Sue Turner.
  - Ordered steps, no self-approval, inbox "only at your step" and progress text were already spine behavior; none of it needed changing.
  - Each step needs a different person: the existing `already_signed` refusal now explains that, and returns 409 instead of 403, as the spec asks ("signing a step twice returns 409").
  - Platform page: `Policy.permission_groups()` now puts every non-app permission (audit, compliance) in one "Platform" column group. Before, `compliance.cosign` would have shown as a second "Platform" group. The fix is in core, so no template changed.
- **Files changed:**
  - `config/policy.yaml`, `seed/users.yaml`
  - `core/approvals.py`, `core/errors.py`, `core/policy.py`, `core/registry.py`
  - `tests/fixtures/users.yaml`, `tests/test_compliance_cosign.py` (new)
  - `docs/specs/compliance-cosign.md` (new), `docs/demo-walkthrough.md` (scene 5), `docs/devin-log.md`
  - Nothing under `apps/` or `templates/`.
- **Tests:** `make test` → 72 passed.
- **Walkthrough:** scene 5 in the browser after a reset: Amy $1,800 on TX-1005 → Mark signs (still pending, nothing paid) → Sue signs from her inbox → paid.
- **Went wrong / caught:** see the pull request description.
- **Wall-clock / ACUs:**

## Session 3: Feature flags (second app)
- **Task:** build the second internal tool by following `playbooks/new-internal-app.md` and `AGENTS.md`. Spec saved as `docs/specs/feature-flags.md`. Rule: don't modify any existing `core/` file.
- **Built:**
  - `apps/flags/`: four checks (flag exists, environment exists, rollout 0–100, actually changes something), risk from config (test → low, production → elevated, production on at full rollout → high), UI and API.
  - `core/connectors/flags_mock.py` (new file): `FlagServiceConnector` protocol + `FlagsMock`, a `MockSystem` that keeps state in `data/ledger.db` and seeds from `seed/flags.yaml` on first use. The app brings it via `AppManifest.connectors`, so `reset_all` covers it.
  - The app declares nothing about approvals or compliance. "engineering lead, then compliance" comes from `policy.yaml` (`high: [app_approver, compliance_cosigner]`) and the existing signer types.
- **Files changed:**
  - New: `apps/flags/__init__.py`, `apps/flags/checks.py`, `apps/flags/manifest.py`, `apps/flags/routes.py`, `apps/flags/service.py`, `core/connectors/flags_mock.py`, `templates/flags/index.html`, `seed/flags.yaml`, `tests/fixtures/flags.yaml`, `tests/test_flags.py`, `docs/specs/feature-flags.md`
  - Edited: `core/identity/mock_provider.py` (one line, approved), `tests/test_identity.py`, `config/policy.yaml`, `config/settings.yaml`, `seed/users.yaml`, `tests/fixtures/users.yaml`, `README.md`, `docs/demo-walkthrough.md` (scenes 6 and 7), `docs/devin-log.md`
- **Reviewer feedback:** Kate filed the same production change twice, and neither could be signed: she's the only engineering lead and can't approve her own request. Added the check "No other change is waiting for this flag and environment". The roles stay as specified (Paul requests, Kate approves), mirroring Amy and Mark. A lead's own production change still has no possible signer in the demo seed. Refusing such requests at submit time would be a spine change, which was proposed and declined. Also added the check "No other change is waiting for this flag and environment", because Kate had filed the same change twice. The underlying spine gap is that any app can create a request nobody is able to sign. Fixing that needs a core change, which is proposed to the user and not made here.
- **Existing core files:** the app itself needed no core change. With the user's explicit approval, one line changed in `core/identity/mock_provider.py`: sign-in cards now follow `seed/users.yaml` order within a department (`ORDER BY department, rowid`) instead of alphabetical, so Paul (requester) shows before Kate (lead), like Amy before Mark. Everything else under `core/` is the new `core/connectors/flags_mock.py`.
- **Tests:** `make test` → 88 passed (72 before + 15 in `tests/test_flags.py` + 1 sign-in order test).
- **Walkthrough:** scenes 6–7 in the browser after a reset. Paul's test-environment change applied. His real-customers change said "Sent for approval: engineering lead, then compliance". Kate signed it, and Amy's $1,800 refund was signed by Mark. Sue's inbox held both (teal Refunds, purple Feature flags). She signed both. The audit log showed both apps in one list.
- **Wall-clock / ACUs:**

