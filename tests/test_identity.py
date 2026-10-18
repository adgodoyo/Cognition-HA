from conftest import auth, make_client, refund_body, sign_in, token


def test_no_sign_in_returns_401(client):
    r = client.post("/api/refunds/preview", json=refund_body("T-SMALL", "small@test.invalid", 100))
    assert r.status_code == 401
    assert r.json()["error"] == "unauthenticated"
    assert client.get("/api/me").status_code == 401


def test_ui_without_sign_in_redirects_to_signin(client):
    r = client.get("/inbox", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/signin"


def test_invalid_token_returns_401_with_instructions(client):
    r = client.get("/api/me", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"
    assert "make -s token" in r.json()["message"]


def test_client_sent_role_is_ignored(client, platform):
    headers = {**auth(platform, "tester_a"), "X-Role": "ops_manager"}
    r = client.get("/api/me?role=ops_manager", headers=headers)
    assert r.status_code == 200
    assert r.json()["role"] == "ops_analyst"

    # A role smuggled into a sign-in form is ignored too.
    client.post("/signin", data={"username": "tester_a", "role": "ops_manager"})
    assert client.get("/api/me").json()["role"] == "ops_analyst"
    assert client.get("/audit").status_code == 403


def test_role_comes_from_server_side_table(client, platform):
    sign_in(client, "tester_a")
    assert client.get("/api/me").json()["username"] == "tester_a"


def test_dev_tokens_do_not_work_without_demo_mode(tmp_path):
    client = make_client(tmp_path, demo_mode=False)
    platform = client.app.state.platform
    r = client.get("/api/me", headers={"Authorization": f"Bearer {token(platform, 'tester_a')}"})
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"


def test_sign_in_chooser_and_reset_need_demo_mode(tmp_path):
    client = make_client(tmp_path, demo_mode=False)
    assert client.post("/signin", data={"username": "tester_a"}).status_code == 403
    assert client.post("/admin/reset").status_code == 404
