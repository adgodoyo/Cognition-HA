"""A large refund can't be split into small ones to skip manager approval."""
from conftest import auth, payments, refund_body, submit


def _limits(app_cfg):
    return app_cfg["self_serve_limits"]


def test_splitting_one_payment_escalates_once_the_total_passes_the_cap(client, platform, app_cfg):
    cap = _limits(app_cfg)["per_transaction_cents"]
    part = cap // 2 + 100  # each part is low risk on its own
    assert part <= app_cfg["elevated_above_cents"]
    first = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", part))
    assert first.json()["status"] == "executed"

    preview = client.post("/api/refunds/preview", json=refund_body("T-BIG", "big@test.invalid", part),
                          headers=auth(platform, "tester_a")).json()
    assert preview["risk"] == "elevated"
    assert "Refunds on this payment" in preview["risk_reason"]

    second = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", part))
    assert second.json()["status"] == "pending" and second.json()["risk"] == "elevated"
    assert payments(platform).payout_count() == 1


def test_per_payment_cap_counts_every_requester(client, platform, app_cfg):
    part = _limits(app_cfg)["per_transaction_cents"] // 2 + 100
    submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", part))
    r = submit(client, platform, "boss_a", refund_body("T-BIG", "big@test.invalid", part))
    assert r.json()["status"] == "pending"


def test_daily_cap_per_requester_across_payments(client, platform, app_cfg):
    daily = _limits(app_cfg)["per_requester_daily_cents"]
    a, b = 40000, 40000
    assert a + b <= daily
    assert submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", a)).json()["status"] == "executed"
    assert submit(client, platform, "tester_a", refund_body("T-PARTIAL", "partial@test.invalid", b)).json()["status"] == "executed"
    c = daily - a - b + 100
    r = submit(client, platform, "tester_a", refund_body("T-SMALL", "small@test.invalid", c))
    assert r.json()["status"] == "pending"
    # Someone else's allowance is untouched.
    r = submit(client, platform, "boss_a", refund_body("T-SMALL", "small@test.invalid", 1000))
    assert r.json()["status"] == "executed"


def test_manager_signed_refunds_do_not_use_up_the_cap(client, platform, app_cfg):
    big = app_cfg["elevated_above_cents"] + 100
    pending = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", big)).json()
    assert client.post(f"/api/approvals/{pending['id']}/sign", headers=auth(platform, "boss_a")).json()["status"] == "executed"
    r = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", 10000))
    assert r.json()["status"] == "executed"


def test_inbox_shows_executed_requests_to_requester_and_approver(client, platform):
    from conftest import sign_in
    submit(client, platform, "tester_a", refund_body("T-SMALL", "small@test.invalid", 1000))
    sign_in(client, "tester_a")
    assert "Refund $10.00 on T-SMALL" in client.get("/inbox").text
    sign_in(client, "boss_a")
    page = client.get("/inbox").text
    assert "Recently decided in apps you approve" in page and "Refund $10.00 on T-SMALL" in page


def test_signed_out_home_links_to_platform(client):
    page = client.get("/", follow_redirects=False)
    assert page.status_code == 200
    assert 'href="/platform"' in page.text and 'href="/signin"' in page.text
