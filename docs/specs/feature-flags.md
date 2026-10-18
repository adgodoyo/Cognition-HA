# Spec: Feature flags app

The client's second internal tool on the platform. Build it by following `playbooks/new-internal-app.md` and `AGENTS.md`.

**Rule that matters most:** don't modify any existing file in `core/`. The app should get identity, approvals, audit and the compliance rule from the spine without asking for them. If a core change looks unavoidable, stop and explain why before making it.

## Goal
Engineers change feature flags safely. Risky production changes need the right signatures.

## Data (`seed/flags.yaml`)
Three flags. Each has two environments, test and production, and each environment holds `enabled` and `rollout_percent` (0–100).

| Flag | Description | Test | Production |
|---|---|---|---|
| instant-payouts, Instant payouts | Same-day payouts to merchants | off, 0% | off, 0% |
| new-checkout, New checkout | Redesigned checkout for card payments | on, 100% | on, 25% |
| kyc-v2-scoring, KYC v2 scoring | New identity-risk scoring model | on, 50% | off, 0% |

## Connector
A new file, `core/connectors/flags_mock.py`, implementing `FlagServiceConnector`:
- `get_flags`, `get_flag`, `change_count`.
- `apply_change` with an idempotency key. Applying the same change twice changes nothing.
- It keeps its state with the other mock external systems and seeds itself from `seed/flags.yaml` on first use, so a demo reset clears it.

## People and roles (`policy.yaml`, `seed/users.yaml`)
- `paul`, Paul Reed, Software engineer, Engineering, role `engineer`: `flags.change` ("Change feature flags").
- `kate`, Kate Hall, Engineering lead, Engineering, role `eng_lead`: `flags.change`, `flags.approve` ("Approve production flag changes"), `audit.read`.
- Operations roles get no flag permissions.

## Settings (`settings.yaml`, read by the app)
- `color: purple`
- `approver_label: "engineering lead"`
- Environment labels: test → "Test environment", production → "Real customers".
- Production environment: `production`.
- Full rollout: 100%.

## Risk levels
- Any change in test: **low**. Applies immediately, still audited.
- Any change in production: **elevated**.
- A production change that turns the flag on at full rollout: **high**.

The app only declares these levels. What each level requires comes from the policy, so nothing compliance-specific goes in this app.

## Checks
- The flag exists.
- The environment exists.
- `rollout_percent` is between 0 and 100.
- The change actually changes something.

## UI (`/apps/flags`)
- A table with flags as rows and the two environments as columns.
- Each cell shows On or Off and "% of customers", with a small change form: an On checkbox, a percentage, and Apply change.
- A low-risk change shows "Applied: Instant payouts: Test environment → on at 100%".
- A change that needs signatures shows "Sent for approval: …", naming the signers in order. The cell keeps its current value, with a yellow Pending chip and the progress.
- Inbox lines read "Instant payouts: Real customers → on at 100%".

## API
- `GET /api/flags`
- `POST /api/flags/changes` (with an `Idempotency-Key` header)

## Tests
- A test-environment change applies immediately.
- A production change is pending with one signer.
- Production on at 100% needs the engineering lead, then compliance.
- The requester can't sign their own.
- Amy gets 403 on any flag change.
- Applying the same change twice changes it once.
- An invalid rollout fails its check.
- The guard test passes.

## Done when
- `make test` is green. The diff adds a new `apps/flags/` folder, the new connector file, a template, config and seed lines, and tests. No existing `core/` file is modified.
- In the browser, after a reset:
  - Paul turns Instant payouts on at 100% in the test environment: applied.
  - He does the same for real customers: "Sent for approval: engineering lead, then compliance".
  - Kate signs it. Separately, Amy requests a high-risk refund ($1,800 on TX-1005) and Mark signs it.
  - Sue's inbox now holds both the refund (teal) and Paul's rollout (purple), waiting for her as compliance.
  - The audit log shows both apps in one list.
- Scenes 6 and 7 are in `docs/demo-walkthrough.md`.
- The README is updated.
- The pull request has screenshots of the flags table, Sue's inbox with both apps, and the audit log.
- `docs/devin-log.md` has an entry listing the files changed, with a one-line confirmation that no existing core file was modified.
