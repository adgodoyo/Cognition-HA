# Playbook: add a new internal app

Input: a one-page spec in `docs/specs/<app>.md`. Output: a pull request with the app, its config, seed data, tests and docs.

1. **Read `AGENTS.md` and the spec.** List every rule in the spec. Each one becomes a check, a risk rule or a test.
2. **Create `apps/<app>/`** with `manifest.py`, `service.py`, `checks.py`, `routes.py`, plus `templates/<app>/index.html`. Use `apps/refunds/` as the reference:
   - `manifest.py`: `build(settings) -> AppManifest(name, title, color, description, permissions, actions, router, nav_path, connectors_used)`.
   - `checks.py`: one `Check(key, label, run)` per rule. `run(payload, ctx)` returns `CheckResult(passed, detail)`. Write the detail in plain language, because people who aren't engineers will read it.
   - `service.py`: turns input into a payload, sets `risk_level(payload)` from the app's config, defines `describe(payload)` and an `execute(payload, idempotency_key, ctx)` that calls a connector.
   - `routes.py`: UI and API routes that call the same service functions. Permissions, signatures and audit all come from `core.approvals`.
3. **Declare actions** as `ActionSpec`s with their checks, a risk level read from config, and execution through a connector.
4. **Config and seed:**
   - `config/policy.yaml`: add `<app>.*` permissions with plain-language labels, and add them to roles.
   - `config/settings.yaml`: add an `apps.<app>` block (color, approver_label, thresholds).
   - `seed/`: add people to `users.yaml` and mock data in `seed/<connector>.yaml`.
   - Test data goes in `tests/fixtures/`, never in seed.
5. **External system?** Add a new typed connector file in `core/connectors/`, mock first: a protocol in its own file, plus a `MockSystem` subclass that keeps state in `data/ledger.db` and seeds from `seed/<name>.yaml`. Alternatively, the app constructs the connector in its manifest (`AppManifest.connectors`). **Do not modify existing core files.** If you think you must, stop and explain why.
6. **Install the app:** add it to `installed_apps` in `config/settings.yaml`.
7. **Write tests for every rule in the spec, negative cases first:** wrong role, self-approval, double execution, each failing check, idempotency. Then run `make test`, including `tests/test_no_demo_literals.py`.
8. **Update** `README.md` and `docs/demo-walkthrough.md`, and add an entry to `docs/devin-log.md`.
