# Demo walkthrough (about 5 minutes)

Start with `make demo` and open http://localhost:8000. `make demo` resets both databases from `seed/` first, so every run starts the same way. You can also reset any time from the button on the Platform page.

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

## 4. A large refund waits for a manager
- Enter `TX-1004`, `john.webb@example.com`, `$1,200`, reason "Order cancelled". Click **Check**: all checks pass, risk is **elevated** (above $500).
- Click **Submit**. The status reads **Waiting for manager approval · 0 of 1: manager**.
- In Amy's request table, the sign button is disabled and explains *"You can't sign your own request."* The API returns the same refusal (`403 self_approval_forbidden`).

## 5. Amy can't read the audit log
- Click **Audit**. Amy gets a red refusal: her role lacks `audit.read`. The navigation never hides pages, so people can see what they're missing.

## 6. Mark approves
- **Sign out**, then sign in as **Mark Evans** (operations manager).
- **Inbox** shows Amy's $1,200 request with its description, five check results, and **Approve** / **Reject** buttons.
- Click **Approve**. The request runs its checks again inside the write transaction, then executes once. The counter goes to **Payouts: 2 · $1,250.00**. Amy's open tabs update within a few seconds.

## 7. The audit story
- Open **Audit** as Mark and filter by app = refunds. Every step has its own row: preview checks, the denied self-signature, Mark's signature, and execution with before/after ledger values. Rows are append-only: the database rejects any `UPDATE` or `DELETE`.

## 8. Platform
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
