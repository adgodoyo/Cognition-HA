import pytest

from conftest import audit_rows, sign_in


def test_platform_page_is_public(client):
    r = client.get("/platform")
    assert r.status_code == 200
    for heading in ("Capabilities × apps", "Permissions by role", "Approval requirements by risk", "Connectors", "Lines of code"):
        assert heading in r.text
    assert "Reset demo data" in r.text


def test_signin_page_lists_people_with_can_and_cannot(client, platform):
    r = client.get("/signin")
    assert "Sign in to Internal Tools" in r.text and "Demo identity provider" in r.text
    assert "Test Analyst One" in r.text and "View the audit log" in r.text


@pytest.mark.parametrize("user, path, status", [
    ("tester_a", "/", 200), ("tester_a", "/inbox", 200), ("tester_a", "/apps/refunds", 200), ("tester_a", "/audit", 403),
    ("boss_a", "/", 200), ("boss_a", "/inbox", 200), ("boss_a", "/apps/refunds", 200), ("boss_a", "/audit", 200),
])
def test_pages_render_for_the_right_people(client, user, path, status):
    sign_in(client, user)
    assert client.get(path).status_code == status


def test_audit_refusal_for_analysts_is_audited(client, platform):
    sign_in(client, "tester_a")
    assert client.get("/audit").status_code == 403
    rows = platform.db.query("SELECT * FROM audit_events WHERE actor = 'tester_a' AND outcome = 'denied'")
    assert rows and rows[-1]["action"] == "audit.view"


def test_home_shows_identity_and_waiting_only_to_signers(client, platform):
    sign_in(client, "tester_a")
    home = client.get("/").text
    assert "Signed in as <strong>Test Analyst One</strong>, Operations analyst" in home
    assert "Waiting for you" not in home
    sign_in(client, "boss_a")
    assert "Waiting for you" in client.get("/").text


def test_nav_shows_audit_link_but_server_refuses_analysts(client):
    sign_in(client, "tester_a")
    assert "Your role can't read the audit log" in client.get("/").text.replace("&#39;", "'")
    assert client.get("/audit").status_code == 403
    sign_in(client, "boss_a")
    assert "Your role can't read the audit log" not in client.get("/").text.replace("&#39;", "'")
    assert client.get("/audit").status_code == 200


def test_payout_counter_on_every_page(client):
    assert "Payouts: 0 · $0.00" in client.get("/platform").text
    sign_in(client, "tester_a")
    assert "Payouts: 0 · $0.00" in client.get("/inbox").text


def test_live_request_for_signed_out_page_is_204(client):
    assert client.get("/inbox", headers={"X-Live": "1"}, follow_redirects=False).status_code == 204


def test_live_poll_of_a_refused_page_is_not_audited(client, platform):
    sign_in(client, "tester_a")
    assert client.get("/audit").status_code == 403
    before = len(audit_rows(platform))
    for _ in range(3):
        assert client.get("/audit", headers={"X-Live": "1"}).status_code == 204
    assert len(audit_rows(platform)) == before
