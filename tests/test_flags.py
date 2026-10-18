"""Feature flags app: risk by environment and rollout, checks, signatures from policy, idempotency.
It declares nothing about compliance; the high-risk co-signer comes from policy.yaml."""
import uuid

from conftest import audit_rows, auth, sign_in

FLAG, NAME = "flag-off", "Fixture Flag Off"


def flags(platform):
    return platform.connectors["flags"]


def state(platform, env, flag=FLAG):
    return flags(platform).get_flag(flag).environments[env]


def change(client, platform, who, env, enabled, percent, flag=FLAG, key=None):
    headers = {**auth(platform, who), "Idempotency-Key": key or uuid.uuid4().hex}
    body = {"flag": flag, "environment": env, "enabled": enabled, "rollout_percent": percent}
    return client.post("/api/flags/changes", json=body, headers=headers)


def sign(client, platform, rid, who):
    return client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, who))


def test_test_environment_change_applies_immediately_and_is_audited(client, platform):
    r = change(client, platform, "eng_a", "test", True, 100)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "executed" and r.json()["risk"] == "low"
    assert r.json()["description"] == f"{NAME}: Test environment → on at 100%"
    assert (state(platform, "test").enabled, state(platform, "test").rollout_percent) == (True, 100)
    assert flags(platform).change_count() == 1
    assert audit_rows(platform, app="flags", outcome="executed", actor="eng_a")


def test_production_change_is_pending_with_one_signer(client, platform, ):
    r = change(client, platform, "eng_a", "production", True, 50)
    body = r.json()
    assert body["status"] == "pending" and body["risk"] == "elevated"
    assert body["progress"] == "0 of 1: engineering lead"
    assert state(platform, "production").enabled is False
    assert sign(client, platform, body["id"], "lead_a").json()["status"] == "executed"
    assert state(platform, "production").rollout_percent == 50


def test_production_on_at_full_rollout_needs_lead_then_compliance(client, platform):
    body = change(client, platform, "eng_a", "production", True, 100).json()
    assert body["risk"] == "high"
    assert body["progress"] == "0 of 2: engineering lead, compliance"
    assert sign(client, platform, body["id"], "cop_a").json()["error"] == "not_your_step"
    first = sign(client, platform, body["id"], "lead_a").json()
    assert first["status"] == "pending" and first["progress"] == "1 of 2: engineering lead ✓, compliance"
    assert flags(platform).change_count() == 0
    assert sign(client, platform, body["id"], "cop_a").json()["status"] == "executed"
    assert state(platform, "production").rollout_percent == 100
    assert flags(platform).change_count() == 1


def test_requester_cannot_sign_their_own(client, platform):
    rid = change(client, platform, "lead_a", "production", True, 30).json()["id"]
    r = sign(client, platform, rid, "lead_a")
    assert r.status_code == 403 and r.json()["error"] == "self_approval_forbidden"
    assert flags(platform).change_count() == 0


def test_operations_roles_get_403_on_any_flag_change(client, platform):
    for who in ("tester_a", "boss_a"):
        for env in ("test", "production"):
            r = change(client, platform, who, env, True, 10)
            assert r.status_code == 403 and r.json()["error"] == "forbidden"
        assert client.get("/api/flags", headers=auth(platform, who)).status_code == 403
    assert flags(platform).change_count() == 0
    assert audit_rows(platform, app="flags", outcome="denied", actor="tester_a")


def test_operations_manager_cannot_sign_flag_changes(client, platform):
    rid = change(client, platform, "eng_a", "production", True, 30).json()["id"]
    assert sign(client, platform, rid, "boss_a").json()["error"] == "forbidden"


def test_same_change_twice_changes_it_once(client, platform):
    key = uuid.uuid4().hex
    first = change(client, platform, "eng_a", "test", True, 40, key=key)
    again = change(client, platform, "eng_a", "test", True, 40, key=key)
    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["id"] == again.json()["id"]
    assert flags(platform).change_count() == 1
    # The connector itself is idempotent too.
    svc = flags(platform)
    a = svc.apply_change(FLAG, "production", True, 5, "same-key")
    b = svc.apply_change(FLAG, "production", True, 5, "same-key")
    assert a == b and svc.change_count() == 2


def _failed(r):
    assert r.status_code == 422 and r.json()["error"] == "checks_failed", r.text
    return {c["key"] for c in r.json()["failed_checks"]}


def test_invalid_rollout_fails_its_check(client, platform):
    assert "rollout" in _failed(change(client, platform, "eng_a", "test", True, 150))
    assert "rollout" in _failed(change(client, platform, "eng_a", "test", True, -1))
    assert flags(platform).change_count() == 0


def test_unknown_flag_environment_and_no_op_fail_their_checks(client, platform):
    assert "flag" in _failed(change(client, platform, "eng_a", "test", True, 10, flag="nope"))
    assert "environment" in _failed(change(client, platform, "eng_a", "staging", True, 10))
    assert _failed(change(client, platform, "eng_a", "test", False, 0)) == {"changes"}


def test_flags_api_lists_state_and_pending(client, platform):
    change(client, platform, "eng_a", "production", True, 100)
    data = {f["flag"]: f for f in client.get("/api/flags", headers=auth(platform, "eng_a")).json()}
    prod = data[FLAG]["environments"]["production"]
    assert prod["label"] == "Real customers" and prod["enabled"] is False
    assert prod["pending"]["progress"] == "0 of 2: engineering lead, compliance"


def test_ui_flash_messages_pending_chip_and_inbox_line(client, platform):
    sign_in(client, "eng_a")
    page = client.get("/apps/flags").text
    assert NAME in page and "% of customers" in page and "Apply change" in page
    form = {"flag": FLAG, "environment": "test", "enabled": "on", "rollout_percent": "100", "idempotency_key": "k1"}
    r = client.post("/apps/flags/changes", data=form)
    assert f"Applied: {NAME}: Test environment → on at 100%" in r.text
    r = client.post("/apps/flags/changes", data={**form, "environment": "production", "idempotency_key": "k2"})
    assert "Sent for approval: engineering lead, then compliance" in r.text
    assert "chip pending" in r.text and "0 of 2: engineering lead, compliance" in r.text
    sign_in(client, "lead_a")
    inbox = client.get("/inbox").text
    assert f"{NAME}: Real customers → on at 100%" in inbox


def test_ops_cannot_open_the_flags_page(client):
    sign_in(client, "tester_a")
    assert client.get("/apps/flags").status_code == 403


def test_reset_restores_flags_from_seed(client, platform):
    change(client, platform, "eng_a", "test", True, 100)
    assert client.post("/admin/reset", follow_redirects=False).status_code == 303
    assert state(platform, "test").enabled is False
    assert flags(platform).change_count() == 0


def test_a_second_change_while_one_is_pending_fails_its_check(client, platform):
    first = change(client, platform, "eng_a", "production", True, 30).json()
    assert first["status"] == "pending"
    assert _failed(change(client, platform, "lead_a", "production", True, 60)) == {"pending"}
    # Other environments and other flags are unaffected.
    assert change(client, platform, "eng_a", "test", True, 30).json()["status"] == "executed"
    sign(client, platform, first["id"], "lead_a")
    assert change(client, platform, "eng_a", "production", False, 0).json()["status"] == "pending"


def test_a_leads_own_production_change_is_signed_by_another_lead(client, platform):
    rid = change(client, platform, "lead_a", "production", True, 30).json()["id"]
    assert sign(client, platform, rid, "lead_a").status_code == 403
    assert sign(client, platform, rid, "lead_b").json()["status"] == "executed"

