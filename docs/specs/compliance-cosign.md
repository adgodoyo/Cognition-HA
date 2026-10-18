# Spec: compliance co-signing for high-risk actions

Source: the client's Compliance team.

> "High-risk actions in any internal app must also be co-signed by Compliance."

This tests the spine's design. A rule like this should be one change in the spine that every app inherits, without touching any app.

## Scope
`core/`, `config/`, `seed/` and `tests/` only. Nothing under `apps/` changes. If an app needs to change, stop and report why: it would mean the spine's design is wrong.

## The change
1. Add permission `compliance.cosign`, labelled "Co-sign high-risk actions in any app".
2. Add role `compliance_officer` (label "Compliance officer") with `compliance.cosign` and `audit.read`.
3. Add a seed user: `sue`, Sue Turner, Compliance officer, department Compliance.
4. Add a signer type `compliance_cosigner` to the registry in `core/approvals.py`: holds `compliance.cosign`, applies to any app, labelled "compliance".
5. In `policy.yaml`, change high risk to `high: [app_approver, compliance_cosigner]`. Signatures stay ordered: the app's approver first, then compliance.
6. A co-signer must differ from the requester and from every earlier signer.
7. Compliance sees an item in *Waiting for your signature* only when it is their step, even though they can't open the app the request came from. Progress reads `1 of 2: manager ✓, compliance`.
8. The Platform page's approval requirements and the sign-in cards update by themselves, because they read `policy.yaml`. Check that they do, without editing templates for it.

## Tests
- A high-risk refund needs both signatures; nothing is paid until the second.
- Compliance signing before the app approver: `403 not_your_step`, audited as denied.
- The same person can't fill both steps.
- Signing a step twice returns 409.
- Low and elevated risk behave exactly as before.
- Every existing test still passes, including the guard test.

## Done when
- `make test` is green.
- The diff touches only the four folders above (plus the docs this request asks for).
- In the browser, after a reset:
  - Amy requests $1,800 on TX-1005, and it shows `0 of 2: manager, compliance`.
  - Mark signs, and it's still pending with nothing paid.
  - Sue, who has no access to Refunds, finds it in her inbox, signs, and it pays.
- That walkthrough is scene 5 of `docs/demo-walkthrough.md`; screenshots of Sue's inbox and the Platform page are in the pull request; `docs/devin-log.md` has an entry listing the files changed.
