# Conventions for every internal app on this platform

1. Apps describe actions, checks and risk levels. The spine (core/) decides what each risk level requires, collects signatures, executes once and audits.
2. Every state-changing action goes through core.approvals.submit. Apps never write to approvals or audit tables.
3. Authorization lives only in core/. Templates may disable buttons using core's can_sign result, never decide on their own.
4. External systems are reached only through typed connectors in core/connectors/, with idempotency keys for writes.
5. No demo records in code: IDs, names, emails and amounts live only in seed/. Rules and thresholds live only in config/. The guard test enforces this.
6. DEMO_MODE gates only the identity chooser, dev tokens and reset. Never business logic.
7. Money is integer cents. Dates in seed data are relative.
8. Every app ships tests for its negative cases: wrong role, self-approval, double execution, each failing check.
9. CI must be green before merge. No new dependencies without a one-line justification.
