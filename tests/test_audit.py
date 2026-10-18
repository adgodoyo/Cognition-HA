import sqlite3

import pytest

from conftest import audit_rows, auth, refund_body, submit


def test_audit_rows_cannot_be_updated_or_deleted(client, platform):
    submit(client, platform, "tester_a", refund_body("T-SMALL", "small@test.invalid", 1000))
    assert audit_rows(platform)
    with platform.db.read() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="audit log is append-only"):
            conn.execute("UPDATE audit_events SET actor = 'someone_else'")
        with pytest.raises(sqlite3.IntegrityError, match="audit log is append-only"):
            conn.execute("DELETE FROM audit_events")


def test_audit_tells_the_story(client, platform, app_cfg):
    amount = app_cfg["elevated_above_cents"] + 100
    rid = submit(client, platform, "tester_a", refund_body("T-BIG", "big@test.invalid", amount)).json()["id"]
    client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, "tester_a"))
    client.post(f"/api/approvals/{rid}/sign", headers=auth(platform, "boss_a"))
    rows = audit_rows(platform, app="refunds")
    assert [(r["actor"], r["action"], r["outcome"]) for r in rows] == [
        ("tester_a", "refund.request", "checked"),
        ("tester_a", "refund.sign", "denied"),
        ("boss_a", "refund.sign", "executed"),
    ]
    assert all(r["request_id"] for r in rows)
    assert '"checks"' in rows[0]["detail"]
