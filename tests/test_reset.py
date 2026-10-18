from conftest import auth, ledger, payments, refund_body, sign_in, submit, token


def test_reset_restores_seeded_state(client, platform, app_cfg):
    old_token = token(platform, "boss_a")
    submit(client, platform, "tester_a", refund_body("T-SMALL", "small@test.invalid", 1000))
    rid = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", app_cfg["elevated_above_cents"] + 1)).json()["id"]
    client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, "boss_a"))
    assert payments(platform).payout_count() == 2
    sign_in(client, "boss_a")

    r = client.post("/admin/reset", follow_redirects=False)
    assert r.status_code == 303

    assert payments(platform).payout_count() == 0
    assert ledger(platform).get_transaction("T-SMALL").refunded_cents == 0
    assert ledger(platform).get_transaction("T-PARTIAL").refunded_cents == 40000
    assert platform.db.query_one("SELECT COUNT(*) AS n FROM approvals")["n"] == 0
    assert platform.db.query_one("SELECT COUNT(*) AS n FROM audit_events")["n"] == 0
    assert token(platform, "boss_a") != old_token
    assert client.get("/api/me").status_code == 401  # everyone is signed out

    new = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", app_cfg["elevated_above_cents"] + 1))
    assert new.json()["id"] == 1  # request IDs start again at 1
