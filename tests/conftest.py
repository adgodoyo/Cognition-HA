"""Tests run against the real config/ (rules live there) but their own seed data in
tests/fixtures/, never the demo seed, and their own temporary databases."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app_main import create_app
from core.settings import load_settings

FIXTURES = Path(__file__).parent / "fixtures"


def make_client(tmp_path: Path, demo_mode: bool = True) -> TestClient:
    settings = load_settings(data_dir=tmp_path, seed_dir=FIXTURES, demo_mode=demo_mode)
    return TestClient(create_app(settings))


@pytest.fixture
def client(tmp_path) -> TestClient:
    return make_client(tmp_path)


@pytest.fixture
def platform(client):
    return client.app.state.platform


@pytest.fixture
def app_cfg(platform) -> dict:
    return platform.settings.app_settings("refunds")


def token(platform, username: str) -> str:
    return platform.identity.dev_token(username)


def auth(platform, username: str) -> dict:
    return {"Authorization": f"Bearer {token(platform, username)}"}


def sign_in(client: TestClient, username: str) -> None:
    r = client.post("/signin", data={"username": username}, follow_redirects=False)
    assert r.status_code == 303


def refund_body(txn: str, email: str, amount_cents: int, reason: str = "Customer request") -> dict:
    return {"transaction_id": txn, "customer_email": email, "amount_cents": amount_cents, "reason": reason}


def submit(client, platform, username: str, body: dict, key: str | None = None):
    headers = {**auth(platform, username), "Idempotency-Key": key or uuid.uuid4().hex}
    return client.post("/api/refunds", json=body, headers=headers)


def payments(platform):
    return platform.connectors["payments"]


def ledger(platform):
    return platform.connectors["ledger"]


def audit_rows(platform, **where) -> list[dict]:
    rows = [dict(r) for r in platform.db.query("SELECT * FROM audit_events ORDER BY id")]
    return [r for r in rows if all(r.get(k) == v for k, v in where.items())]
