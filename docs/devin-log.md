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
- **Tests:** `make test` → 57 passed.
- **Walkthrough:** `docs/demo-walkthrough.md`, clicked through twice in the browser with a reset in between.
- **Went wrong / caught:**
  - The guard test matches whole words, case-insensitively, so the demo username "mark" doesn't false-positive on words like "markupsafe". That also means the HTML `<mark>` tag can't be used in templates.
  - `pytest` needed `pythonpath = . tests` to import `app_main` and `conftest`.
  - Found during the walkthrough: live refresh re-fetched a refused page every few seconds, writing a new "denied" audit row each time. Background polls now get a 204 and are not audited (regression test added). The Audit log link is now shown greyed out to roles without access, and the refusal is red and names the missing permission.
- **Assumptions:** see the pull request description.
