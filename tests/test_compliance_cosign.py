"""High-risk actions in any app need the app's approver, then a compliance co-signer.
Nothing under apps/ knows about compliance: it comes from policy.yaml and the spine."""
import re

from conftest import audit_rows, auth, payments, refund_body, sign_in, submit
from core.policy import Role


def high(app_cfg):
    return app_cfg["high_above_cents"] + 100


def request_high(client, platform, app_cfg, requester="tester_a"):
    r = submit(client, platform, requester, refund_body("T-BIG", "big@test.invalid", high(app_cfg)))
    assert r.status_code == 201, r.text
    return r.json()


def sign(client, platform, rid, who):
    return client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, who))


def grant(platform, role, permission):
    r = platform.policy.roles[role]
    platform.policy.roles[role] = Role(r.key, r.label, r.permissions + (permission,))


def test_policy_requirements(platform):
    assert platform.policy.requirements_for("low") == []
    assert platform.policy.requirements_for("elevated") == ["app_approver"]
    assert platform.policy.requirements_for("high") == ["app_approver", "compliance_cosigner"]


def test_high_risk_needs_both_signatures_and_pays_only_after_the_second(client, platform, app_cfg):
    label = app_cfg["approver_label"]
    req = request_high(client, platform, app_cfg)
    assert req["status"] == "pending" and req["risk"] == "high"
    assert req["progress"] == f"0 of 2: {label}, compliance"

    first = sign(client, platform, req["id"], "boss_a")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "pending"
    assert first.json()["progress"] == f"1 of 2: {label} ✓, compliance"
    assert first.json()["status_text"] == "Waiting for compliance approval"
    assert payments(platform).payout_count() == 0

    second = sign(client, platform, req["id"], "cop_a")
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "executed"
    assert payments(platform).payout_count() == 1


def test_compliance_before_the_app_approver_is_not_your_step_and_audited(client, platform, app_cfg):
    req = request_high(client, platform, app_cfg)
    r = sign(client, platform, req["id"], "cop_a")
    assert r.status_code == 403 and r.json()["error"] == "not_your_step"
    denied = audit_rows(platform, outcome="denied", actor="cop_a")
    assert denied and "not_your_step" in denied[-1]["detail"]
    assert payments(platform).payout_count() == 0


def test_the_same_person_cannot_fill_both_steps(client, platform, app_cfg):
    grant(platform, "ops_manager", "compliance.cosign")
    req = request_high(client, platform, app_cfg)
    assert sign(client, platform, req["id"], "boss_a").status_code == 200
    again = sign(client, platform, req["id"], "boss_a")
    assert again.status_code == 409 and again.json()["error"] == "already_signed"
    assert payments(platform).payout_count() == 0
    assert sign(client, platform, req["id"], "boss_b").json()["status"] == "executed"


def test_cosigner_cannot_be_the_requester(client, platform, app_cfg):
    grant(platform, "ops_manager", "compliance.cosign")
    req = request_high(client, platform, app_cfg, requester="boss_a")
    assert sign(client, platform, req["id"], "boss_b").status_code == 200
    r = sign(client, platform, req["id"], "boss_a")
    assert r.status_code == 403 and r.json()["error"] == "self_approval_forbidden"
    assert payments(platform).payout_count() == 0


def test_signing_a_step_twice_is_409(client, platform, app_cfg):
    req = request_high(client, platform, app_cfg)
    assert sign(client, platform, req["id"], "boss_a").status_code == 200
    assert sign(client, platform, req["id"], "boss_a").status_code == 409
    assert sign(client, platform, req["id"], "cop_a").status_code == 200
    assert sign(client, platform, req["id"], "cop_a").status_code == 409
    assert payments(platform).payout_count() == 1


def test_compliance_cannot_sign_elevated_requests(client, platform, app_cfg):
    rid = submit(client, platform, "tester_a",
                 refund_body("T-BIG", "big@test.invalid", app_cfg["elevated_above_cents"] + 100)).json()["id"]
    r = sign(client, platform, rid, "cop_a")
    assert r.status_code == 403 and r.json()["error"] == "forbidden"
    assert sign(client, platform, rid, "boss_a").json()["status"] == "executed"


def _waiting_section(page: str) -> str:
    return page.split('id="inbox-waiting"', 1)[1].split('id="inbox-mine"', 1)[0]


def test_compliance_inbox_shows_the_item_only_at_their_step(client, platform, app_cfg):
    req = request_high(client, platform, app_cfg)
    sign_in(client, "cop_a")
    assert client.get("/apps/refunds").status_code == 403
    assert f"#{req['id']} " not in _waiting_section(client.get("/inbox").text)

    sign(client, platform, req["id"], "boss_a")
    waiting = _waiting_section(client.get("/inbox").text)
    assert f"#{req['id']} " in waiting and "compliance" in waiting
    r = client.post(f"/approvals/{req['id']}/sign", data={"next": "/inbox"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert payments(platform).payout_count() == 1
    assert f"#{req['id']} " not in _waiting_section(client.get("/inbox").text)


def test_platform_page_and_signin_cards_read_the_new_policy(client):
    platform_page = client.get("/platform").text
    assert "app_approver → compliance_cosigner" in platform_page
    assert "needs manager, then compliance" in platform_page
    assert "Compliance officer" in platform_page
    # audit.read and compliance.cosign aren't app permissions: one "Platform" column group, not two
    assert len(re.findall(r"<th colspan=\"\d+\"[^>]*>\s*Platform</th>", platform_page)) == 1
    signin = client.get("/signin").text
    assert "Test Compliance One" in signin and "Co-sign high-risk actions in any app" in signin
