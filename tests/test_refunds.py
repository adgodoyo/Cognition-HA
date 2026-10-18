from conftest import auth, ledger, payments, refund_body, submit


def test_risk_levels_follow_config_thresholds(client, platform, app_cfg):
    def risk(amount):
        r = client.post("/api/refunds/preview", json=refund_body("T-BIG", "big@test.invalid", amount),
                        headers=auth(platform, "tester_a"))
        return r.json()["risk"]

    elevated, high = app_cfg["elevated_above_cents"], app_cfg["high_above_cents"]
    assert risk(elevated) == "low"
    assert risk(elevated + 1) == "elevated"
    assert risk(high) == "elevated"
    assert risk(high + 1) == "high"


def test_low_risk_refund_executes_immediately(client, platform, app_cfg):
    amount = min(app_cfg["elevated_above_cents"], 10000)
    r = submit(client, platform, "tester_a", refund_body("T-SMALL", "small@test.invalid", amount))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "executed"
    assert payments(platform).payout_count() == 1
    assert ledger(platform).get_transaction("T-SMALL").refunded_cents == amount


def test_elevated_refund_is_pending_with_no_payouts(client, platform, app_cfg):
    amount = app_cfg["elevated_above_cents"] + 100
    r = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", amount))
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending" and body["risk"] == "elevated"
    assert body["status_text"] == f"Waiting for {app_cfg['approver_label']} approval"
    assert body["progress"] == f"0 of 1: {app_cfg['approver_label']}"
    assert payments(platform).payout_count() == 0


def test_missing_reason_is_rejected(client, platform):
    r = submit(client, platform, "tester_a", refund_body("T-SMALL", "small@test.invalid", 1000, reason=""))
    assert r.status_code == 422


def test_ui_flow_check_then_submit(client, platform, app_cfg):
    from conftest import sign_in

    sign_in(client, "tester_a")
    form = {"transaction_id": "T-BIG", "customer_email": "big@test.invalid",
            "amount": f"{(app_cfg['elevated_above_cents'] + 100) / 100:.2f}", "reason": "Damaged", "idempotency_key": "ui-1"}
    page = client.post("/apps/refunds/check", data=form)
    assert page.status_code == 200
    assert "Transaction exists in the ledger" in page.text and "needs " + app_cfg["approver_label"] in page.text
    r = client.post("/apps/refunds", data=form, follow_redirects=False)
    assert r.status_code == 303
    again = client.post("/apps/refunds", data=form, follow_redirects=False)  # double-click
    assert again.status_code == 303
    assert platform.db.query_one("SELECT COUNT(*) AS n FROM approvals")["n"] == 1
    assert "Waiting for " + app_cfg["approver_label"] + " approval" in client.get("/apps/refunds").text
