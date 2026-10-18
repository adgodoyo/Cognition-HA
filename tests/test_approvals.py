import threading

from conftest import audit_rows, auth, ledger, payments, refund_body, sign_in, submit


def elevated(app_cfg):
    return app_cfg["elevated_above_cents"] + 5000


def test_requester_cannot_sign_their_own(client, platform, app_cfg):
    rid = submit(client, platform, "boss_a", refund_body("T-BIG", "big@test.invalid", elevated(app_cfg))).json()["id"]
    r = client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, "boss_a"))
    assert r.status_code == 403
    assert r.json()["error"] == "self_approval_forbidden"
    assert r.json()["message"] == "You can't sign your own request."
    denied = audit_rows(platform, outcome="denied", actor="boss_a")
    assert denied and "self_approval_forbidden" in denied[-1]["detail"]
    assert payments(platform).payout_count() == 0


def test_person_without_approve_permission_gets_403(client, platform, app_cfg):
    rid = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", elevated(app_cfg))).json()["id"]
    r = client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, "tester_b"))
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"
    assert audit_rows(platform, outcome="denied", actor="tester_b")


def test_manager_signs_executes_once_and_second_sign_is_409(client, platform, app_cfg):
    amount = elevated(app_cfg)
    rid = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", amount)).json()["id"]
    r = client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, "boss_a"))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "executed"
    assert r.json()["progress"] == f"1 of 1: {app_cfg['approver_label']} ✓"
    assert payments(platform).payout_count() == 1
    assert ledger(platform).get_transaction("T-BIG").refunded_cents == amount

    again = client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, "boss_a"))
    assert again.status_code == 409 and again.json()["error"] == "already_decided"
    other = client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, "boss_b"))
    assert other.status_code == 409
    assert payments(platform).payout_count() == 1


def test_concurrent_signatures_pay_once(client, platform, app_cfg):
    rid = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", elevated(app_cfg))).json()["id"]
    codes = []
    def go(user):
        codes.append(client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, user)).status_code)
    threads = [threading.Thread(target=go, args=(u,)) for u in ("boss_a", "boss_b", "boss_a", "boss_b")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes).count(200) == 1
    assert payments(platform).payout_count() == 1


def test_same_idempotency_key_creates_one_request(client, platform, app_cfg):
    body = refund_body("T-BIG", "big@test.invalid", elevated(app_cfg))
    first = submit(client, platform, "tester_a", body, key="same-key")
    second = submit(client, platform, "tester_a", body, key="same-key")
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert platform.db.query_one("SELECT COUNT(*) AS n FROM approvals")["n"] == 1


def test_idempotency_key_reused_for_a_different_request_is_409(client, platform, app_cfg):
    submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", elevated(app_cfg)), key="k")
    r = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", elevated(app_cfg) + 1), key="k")
    assert r.status_code == 409 and r.json()["error"] == "idempotency_key_conflict"


def test_missing_idempotency_key_is_400(client, platform):
    r = client.post("/api/refunds", json=refund_body("T-SMALL", "small@test.invalid", 100), headers=auth(platform, "tester_a"))
    assert r.status_code == 400 and r.json()["error"] == "idempotency_key_required"


def test_two_requests_exceeding_refundable_amount_second_is_blocked(client, platform, app_cfg):
    # T-BIG is $3,000.00; two pending $1,600 requests would exceed it.
    amount = app_cfg["high_above_cents"] + 10000
    first = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", amount))
    assert first.status_code == 201 and first.json()["status"] == "pending"
    second = submit(client, platform, "tester_b", refund_body("T-BIG", "big@test.invalid", amount))
    assert second.status_code == 422
    assert second.json()["failed_checks"][0]["key"] == "amount"
    assert "open requests $1,600.00" in second.json()["failed_checks"][0]["detail"]


def test_reject_requires_reason_and_frees_the_amount(client, platform, app_cfg):
    amount = app_cfg["high_above_cents"] + 10000
    rid = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", amount)).json()["id"]
    r = client.post(f"/api/approvals/{rid}/reject", json={"reason": " "}, headers=auth(platform, "boss_a"))
    assert r.status_code == 422 and r.json()["error"] == "reason_required"
    r = client.post(f"/api/approvals/{rid}/reject", json={"reason": "Duplicate"}, headers=auth(platform, "boss_a"))
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert submit(client, platform, "tester_b", refund_body("T-BIG", "big@test.invalid", amount)).status_code == 201
    assert payments(platform).payout_count() == 0


def test_unknown_request_is_404(client, platform):
    r = client.post("/api/approvals/999/sign", headers=auth(platform, "boss_a"))
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_connector_failure_marks_request_failed(client, platform, app_cfg):
    rid = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", elevated(app_cfg))).json()["id"]
    payments(platform).fail_next("processor timeout")
    r = client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, "boss_a"))
    assert r.status_code == 200
    assert r.json()["status"] == "failed" and "processor timeout" in r.json()["error"]
    assert payments(platform).payout_count() == 0
    assert audit_rows(platform, outcome="failed")


def test_payment_processor_honours_idempotency_and_refuses_over_refund(platform):
    p = payments(platform)
    first = p.refund("T-SMALL", 1000, "key-1")
    assert p.refund("T-SMALL", 1000, "key-1") == first
    assert p.payout_count() == 1
    import pytest
    from core.connectors.base import PaymentError
    with pytest.raises(PaymentError):
        p.refund("T-SMALL", 30000, "key-2")
    assert ledger(platform).get_transaction("T-SMALL").refunded_cents == 1000


def test_can_sign_drives_the_ui_buttons(client, platform, app_cfg):
    rid = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", elevated(app_cfg))).json()["id"]
    sign_in(client, "tester_a")
    page = client.get("/apps/refunds").text
    assert "You can&#39;t sign your own request." in page
    sign_in(client, "boss_a")
    inbox = client.get("/inbox").text
    assert f"#{rid}" in inbox
    r = client.post(f"/approvals/{rid}/sign", data={"next": "/inbox"}, follow_redirects=False)
    assert r.status_code == 303
    assert payments(platform).payout_count() == 1
