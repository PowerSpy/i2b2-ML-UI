"""Accounts, sessions, CSRF and throttling.

Step 2 creates the machinery but gates nothing: the existing routes are still
open. These tests cover the machinery itself, so that step 3 — which turns it
on everywhere at once — is a config change rather than a leap of faith.
"""

import pytest
from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"


@pytest.fixture
def client(app_home):
    from app.main import app
    return TestClient(app)


@pytest.fixture
def custodian(app_home):
    from app.core import auth, passwords
    from app.core.authz import Role

    auth.create_user("alice", passwords.hash_password(PASSWORD), Role.CUSTODIAN,
                     display_name="Alice")
    return "alice"


def login(client, username=PASSWORD and "alice", password=PASSWORD):
    return client.post("/api/auth/login",
                       json={"username": username, "password": password})


# --------------------------------------------------------------------------
# passwords


def test_password_round_trip_and_rejections(app_home):
    from app.core import passwords

    stored = passwords.hash_password(PASSWORD)
    assert passwords.verify_password(PASSWORD, stored)
    assert not passwords.verify_password("wrong", stored)
    # A corrupt row must fail the login, not 500 the endpoint.
    assert not passwords.verify_password(PASSWORD, "garbage")
    assert not passwords.verify_password(PASSWORD, "")
    # The plaintext must not be recoverable from the stored form.
    assert PASSWORD not in stored


def test_short_passwords_are_refused(app_home):
    from app.core import passwords

    with pytest.raises(passwords.PasswordError):
        passwords.hash_password("short")


def test_hashes_are_salted(app_home):
    from app.core import passwords

    assert passwords.hash_password(PASSWORD) != passwords.hash_password(PASSWORD)


# --------------------------------------------------------------------------
# login


def test_login_sets_both_cookies(client, custodian):
    res = login(client)
    assert res.status_code == 200

    from app.core import auth

    assert auth.COOKIE_NAME in res.cookies
    assert auth.CSRF_COOKIE in res.cookies
    body = res.json()
    assert body["username"] == "alice"
    assert body["role"] == "custodian"
    assert body["csrf_token"]


def test_session_cookie_is_httponly_and_csrf_cookie_is_not(client, custodian):
    """The whole point of the split: one must be unreadable from JS, the other
    must be readable so the frontend can echo it back."""
    res = login(client)
    jar = {c.split("=")[0].strip(): c for c in res.headers.get_list("set-cookie")}

    from app.core import auth

    session = next(v for k, v in jar.items() if k == auth.COOKIE_NAME)
    csrf = next(v for k, v in jar.items() if k == auth.CSRF_COOKIE)
    assert "httponly" in session.lower()
    assert "httponly" not in csrf.lower()
    assert "samesite=lax" in session.lower()


def test_wrong_password_and_unknown_user_are_indistinguishable(client, custodian):
    """Anything that differs turns this into a username oracle."""
    bad_pw = client.post("/api/auth/login",
                         json={"username": "alice", "password": "wrong-one-here"})
    no_user = client.post("/api/auth/login",
                          json={"username": "nobody", "password": "wrong-one-here"})

    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json()["detail"] == no_user.json()["detail"]


def test_the_raw_token_is_never_stored(client, custodian):
    from app.core import auth, store

    res = login(client)
    token = res.cookies[auth.COOKIE_NAME]

    rows = store.query("SELECT token_hash FROM app_session")
    assert rows and rows[0]["token_hash"] != token
    assert rows[0]["token_hash"] == auth.token_hash(token)


def test_disabled_user_cannot_log_in(client, custodian):
    from app.core import auth

    auth.set_disabled("alice", True)
    assert login(client).status_code == 401


# --------------------------------------------------------------------------
# me / logout


def test_me_requires_a_session(client, custodian):
    assert client.get("/api/auth/me").status_code == 401


def test_me_after_login(client, custodian):
    login(client)
    body = client.get("/api/auth/me").json()
    assert body["username"] == "alice"
    assert body["display_name"] == "Alice"
    assert body["role"] == "custodian"


def test_logout_ends_the_session(client, custodian):
    login(client)
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------
# CSRF


def _fake_request(method: str, token: str, csrf: str | None = None):
    """A Request carrying just enough for `current_principal`.

    The dependency is exercised directly because no existing route depends on
    it yet - step 3 mounts it. Going through a real route here would test
    whichever handler happened to be picked, and on this machine that means a
    stopped Postgres container rather than the CSRF check.
    """
    from starlette.requests import Request

    from app.core import auth

    headers = [(b"cookie", f"{auth.COOKIE_NAME}={token}".encode())]
    if csrf is not None:
        headers.append((auth.CSRF_HEADER.lower().encode(), csrf.encode()))

    return Request({
        "type": "http", "method": method, "path": "/api/x",
        "headers": headers, "query_string": b"",
        "client": ("127.0.0.1", 1234),
    })


def test_unsafe_request_without_csrf_header_is_rejected(client, custodian):
    """SameSite=Lax is the first lock; this is the second."""
    import asyncio

    from fastapi import HTTPException

    from app.api.deps import current_principal
    from app.core import auth

    token = login(client).cookies[auth.COOKIE_NAME]

    with pytest.raises(HTTPException) as e:
        asyncio.run(current_principal(_fake_request("DELETE", token)))
    assert e.value.status_code == 403
    assert "csrf" in e.value.detail.lower()


def test_unsafe_request_with_a_wrong_csrf_token_is_rejected(client, custodian):
    import asyncio

    from fastapi import HTTPException

    from app.api.deps import current_principal
    from app.core import auth

    token = login(client).cookies[auth.COOKIE_NAME]

    with pytest.raises(HTTPException) as e:
        asyncio.run(current_principal(_fake_request("DELETE", token, "wrong")))
    assert e.value.status_code == 403


def test_unsafe_request_with_the_right_csrf_token_passes(client, custodian):
    import asyncio

    from app.api.deps import current_principal
    from app.core import auth

    res = login(client)
    token = res.cookies[auth.COOKIE_NAME]
    csrf = res.json()["csrf_token"]

    principal = asyncio.run(current_principal(_fake_request("DELETE", token, csrf)))
    assert principal.username == "alice"


def test_safe_requests_do_not_need_the_csrf_header(client, custodian):
    login(client)
    assert client.get("/api/auth/me").status_code == 200


# --------------------------------------------------------------------------
# sessions


def test_expired_session_is_rejected_and_removed(client, custodian):
    from datetime import UTC, datetime, timedelta

    from app.core import auth, store

    login(client)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    store.write("UPDATE app_session SET expires_at = ?", (past,))

    assert client.get("/api/auth/me").status_code == 401
    assert store.query("SELECT 1 FROM app_session") == []


def test_password_change_ends_existing_sessions(client, custodian):
    from app.core import auth, passwords

    login(client)
    assert client.get("/api/auth/me").status_code == 200

    auth.set_password("alice", passwords.hash_password("a different passphrase"))
    assert client.get("/api/auth/me").status_code == 401


def test_role_change_ends_existing_sessions(client, custodian):
    """A demotion has to take effect now, not when the session expires."""
    from app.core import auth
    from app.core.authz import Role

    login(client)
    auth.set_role("alice", Role.RESEARCHER)
    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------
# throttling and bootstrap


def test_repeated_failures_are_throttled(client, custodian):
    from app.core import auth

    for _ in range(auth.MAX_PER_USER):
        client.post("/api/auth/login",
                    json={"username": "alice", "password": "wrong-one-here"})

    res = login(client)  # correct password, but the window is closed
    assert res.status_code == 429


def test_no_accounts_yields_503_naming_the_command(client, app_home):
    """Unusable rather than open, and the error says exactly what to run."""
    res = client.get("/api/auth/me")
    assert res.status_code == 503
    assert "app.cli create-user" in res.json()["detail"]


def test_login_events_are_audited_without_the_password(client, custodian):
    from conftest import audit_text

    client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    client.post("/api/auth/login", json={"username": "alice", "password": "wrong-one-here"})

    from app.core import store

    kinds = [r["kind"] for r in store.query("SELECT kind FROM audit_event")]
    assert "login_ok" in kinds
    assert "login_failed" in kinds

    blob = " ".join(str(tuple(r)) for r in store.query("SELECT * FROM audit_event"))
    assert PASSWORD not in blob
    assert "wrong-one-here" not in blob
