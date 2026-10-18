import pytest

from conftest import auth, ledger, payments, refund_body, submit


def preview(client, platform, body, user="tester_a"):
    r = client.post("/api/refunds/preview", json=body, headers=auth(platform, user))
    assert r.status_code == 200, r.text
    return {c["key"]: c for c in r.json()["checks"]}, r.json()


@pytest.mark.parametrize(
    "body, failing, phrase",
    [
        (refund_body("T-NOPE", "x@test.invalid", 1000), "exists", "No transaction"),
        (refund_body("T-PENDING", "pending@test.invalid", 1000), "settled", "the money hasn't arrived yet"),
        (refund_body("T-DISPUTED", "disputed@test.invalid", 1000), "settled", "chargeback"),
        (refund_body("T-SMALL", "someone.else@test.invalid", 1000), "customer", "doesn't match"),
        (refund_body("T-OLD", "old@test.invalid", 1000), "window", "outside"),
        (refund_body("T-PARTIAL", "partial@test.invalid", 60001), "amount", "more than can be refunded"),
        (refund_body("T-SMALL", "small@test.invalid", 0), "amount", "more than zero"),
    ],
)
def test_each_check_fails_in_its_own_case(client, platform, body, failing, phrase):
    checks, result = preview(client, platform, body)
    assert not checks[failing]["passed"]
    assert phrase in checks[failing]["detail"]
    assert result["all_passed"] is False
    if failing != "exists":  # everything else about these requests is fine
        others = [k for k, c in checks.items() if k != failing and not c["passed"]]
        assert others == []


def test_email_match_is_case_insensitive(client, platform):
    checks, result = preview(client, platform, refund_body("T-SMALL", "SMALL@Test.Invalid", 1000))
    assert result["all_passed"], checks


def test_amount_breakdown_is_shown(client, platform):
    checks, _ = preview(client, platform, refund_body("T-PARTIAL", "partial@test.invalid", 1000))
    detail = checks["amount"]["detail"]
    assert "Paid $1,000.00" in detail and "already refunded $400.00" in detail and "= $600.00 refundable" in detail


def test_preview_writes_nothing(client, platform):
    before_audit = platform.db.query_one("SELECT COUNT(*) AS n FROM audit_events")["n"]
    preview(client, platform, refund_body("T-BIG", "big@test.invalid", 100000))
    preview(client, platform, refund_body("T-PENDING", "pending@test.invalid", 100))
    assert platform.db.query_one("SELECT COUNT(*) AS n FROM approvals")["n"] == 0
    assert platform.db.query_one("SELECT COUNT(*) AS n FROM audit_events")["n"] == before_audit
    assert payments(platform).payout_count() == 0


def test_ledger_change_between_preview_and_submit_returns_422(client, platform):
    body = refund_body("T-SMALL", "small@test.invalid", 25000)
    _, result = preview(client, platform, body)
    assert result["all_passed"]
    # Someone else refunds most of the payment directly at the processor in the meantime.
    payments(platform).refund("T-SMALL", 20000, "outside-the-platform")
    assert ledger(platform).get_transaction("T-SMALL").refunded_cents == 20000
    r = submit(client, platform, "tester_a", body)
    assert r.status_code == 422
    assert r.json()["error"] == "checks_failed"
    assert [c["key"] for c in r.json()["failed_checks"]] == ["amount"]
