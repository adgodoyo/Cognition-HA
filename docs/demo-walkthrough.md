# Demo walkthrough (about 5 minutes)

Start with `make demo` and open http://localhost:8000. Signed out, the home page links to **Sign in** and **Platform**. `make demo` resets both databases from `seed/` first, so every run starts the same way. You can also reset any time from the button on the Platform page.

## 1. Sign in as Amy (operations analyst)
- The sign-in page lists the two demo people. Each card shows what that person **can** and **cannot** do. The lists are generated from `config/policy.yaml`.
- Choose **Amy Clark**. The header shows her name and role, plus the shared counter **Payouts: 0 · $0.00**.

## 2. The checks catch a bad refund
- Open **Refunds**. Enter `TX-1006`, `luke.ross@example.com`, `$100`, then click **Check**.
- The ledger preview shows the original payment. Four checks pass. **Original payment has settled** fails in red: *"Status is disputed: the customer opened a chargeback, so the bank is already handling this money."*
- The **Submit** button is disabled, and the server would refuse the request anyway.
- Optional: try `TX-1007` (outside the 90-day refund window) or `TX-1008` (payment still pending).

## 3. A small refund executes immediately
- Enter `TX-1001`, `laura.hill@example.com`, `$50`, reason "Damaged item". Click **Check**: all five checks pass, risk is **low**.
- Click **Submit**. The request is **Executed** right away, because low risk needs no signature. The header counter goes to **Payouts: 1 · $50.00**.

## 3b. Splitting a refund doesn't get around the manager
- Still as Amy, refund `$300` on `TX-1005` (`emma.ford@example.com`), reason "Partial return". Check → low, Submit → **Executed**. Counter: **Payouts: 2 · $350.00**.
- Check another `$300` on `TX-1005`. Risk is **elevated**, with the reason *"Raised from low: Refunds on this payment: $300.00 already approved without a signature + $300.00 = $600.00, over the $500.00 limit."* Submit it: it waits for a manager instead of executing.
- The limits are in `config/settings.yaml` → `apps.refunds.self_serve_limits`: one cap per payment (counting everyone's requests) and a 24-hour cap per person (counting all payments).

## 4. A large refund waits for a manager
- Enter `TX-1004`, `john.webb@example.com`, `$1,200`, reason "Order cancelled". Click **Check**: all checks pass, risk is **elevated** (above $500).
- Click **Submit**. The status reads **Waiting for manager approval · 0 of 1: manager**.
- In Amy's request table, the sign button is disabled and explains *"You can't sign your own request."* The API returns the same refusal (`403 self_approval_forbidden`).

## 5. High risk needs compliance too
Run this scene on its own from a reset (Platform → **Reset demo data**). Scenes 6–8 continue from where scene 4 left off, so either do this scene last or reset and replay scenes 1–4 afterwards.
- Sign in as **Amy**. In **Refunds**, enter `TX-1005`, `emma.ford@example.com`, `$1,800`, reason "Order cancelled". Click **Check**: risk is **high**, and it *needs manager, then compliance*.
- Click **Submit**. The request shows **0 of 2: manager, compliance**. Nothing is paid.
- Sign out and sign in as **Mark**. His inbox shows the request. Click **Sign**: it now reads **1 of 2: manager ✓, compliance**, still pending, and the counter still says **Payouts: 0**.
- Sign out and sign in as **Sue Turner** (Compliance officer). The Refunds tile says *No access*, and opening `/apps/refunds` is refused. Her **Inbox** has the request under *Waiting for your signature*, because it's now her step. Before Mark signed, it wasn't there.
- Click **Sign**. The request executes once: **Payouts: 1 · $1,800.00**.
- Nothing under `apps/` changed for this. The rule is one line in `config/policy.yaml` (`high: [app_approver, compliance_cosigner]`) plus the `compliance_cosigner` signer type in `core/approvals.py`. The Platform page's approval table and the sign-in cards picked it up from `policy.yaml`.

## 6. Amy can't read the audit log
- The **Audit log** link is greyed out for Amy, but she can still click it. She gets a red refusal: *"Your role (Operations analyst) does not have the permission: View the audit log."* The refusal itself goes into the audit log.

## 7. Mark approves
- **Sign out**, then sign in as **Mark Evans** (operations manager).
- **Inbox** shows Amy's pending requests (the $1,200 one, plus the escalated $300 split) waiting for his signature, and below that, recently decided requests in apps he approves, including Amy's self-approved ones. Amy's own inbox lists her recent requests with their status.
- The $1,200 request shows with its reason, requester, risk, progress (`0 of 1: manager`), and **Sign** / **Reject** buttons.
- Click **Sign**. The request runs its checks again inside the write transaction, then executes once. The counter goes to **Payouts: 3 · $1,550.00**. Amy's open tabs update within a few seconds.

## 8. The audit story
- Open **Audit log** as Mark. Every step has its own row, newest first:
  - Amy's $50 and first $300 requests, `executed`, with before/after ledger values.
  - Amy's second $300 request, `checked`, with `risk_reason` explaining the escalation.
  - Amy's $1,200 request, `checked`: all checks passed, now waiting.
  - Amy's `audit.view` attempt, `denied`, highlighted in red.
  - Mark's signature, `executed`, with before/after ledger values.
- Click **Refunds** to filter to that app. Checks in the preview panel are read-only, so they don't write audit rows. Rows are append-only: the database rejects any `UPDATE` or `DELETE`.

## 9. Platform
- Open **Platform**. It shows the capability matrix (what the spine provides versus what each app declares), role permissions, approval rules for each risk level, connectors, and how many lines of code the Refunds app needed.
- Click **Reset demo data** to start over.

## Same flow with curl (API)
```bash
T=$(make -s token user=amy); M=$(make -s token user=mark)
curl -s -X POST localhost:8000/api/refunds/preview -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' \
  -d '{"transaction_id":"TX-1006","customer_email":"luke.ross@example.com","amount_cents":10000}'
curl -s -X POST localhost:8000/api/refunds -H "Authorization: Bearer $T" -H 'Idempotency-Key: demo-1' \
  -H 'Content-Type: application/json' \
  -d '{"transaction_id":"TX-1004","customer_email":"john.webb@example.com","amount_cents":120000,"reason":"Order cancelled"}'
curl -s -X POST localhost:8000/api/approvals/1/sign -H "Authorization: Bearer $T"   # 403 self_approval_forbidden
curl -s -X POST localhost:8000/api/approvals/1/sign -H "Authorization: Bearer $M"   # executed
curl -s -X POST localhost:8000/api/approvals/1/sign -H "Authorization: Bearer $M"   # 409 already_decided
```
Dev tokens exist only when `DEMO_MODE=1`, and a reset regenerates them.
