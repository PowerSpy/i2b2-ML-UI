"""A request produces a traceable chain of audit rows.

The value of the audit log is not that events exist, it is that they share a
`request_id` — so "what did this call actually do to the warehouse" is one
query rather than an inference from timestamps. These tests assert the chain,
not just the rows.
"""

import json

from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


def test_health_carries_the_build_stamp(app_home):
    from app.core import buildinfo

    body = _client().get("/api/health").json()

    assert body["status"] == "ok"
    assert body["git_sha"] == buildinfo.git_sha()
    assert body["release"].startswith(buildinfo.VERSION)
    assert body["uptime_sec"] >= 0


def test_health_is_not_audited(app_home):
    """The UI polls it constantly; logging it would bury everything else."""
    from app.core import store

    _client().get("/api/health")

    assert store.query("SELECT 1 FROM audit_event WHERE kind='request'") == []


def test_every_response_carries_a_request_id(app_home):
    res = _client().get("/api/health")
    assert res.headers.get("X-Request-Id")


def test_container_calls_are_attributed_to_their_request(app_home, fake_exec):
    """The chain that makes the log useful: one request, one id, every
    container call underneath it carrying that same id."""
    from app.core import store

    res = _client().get("/api/watcher")
    request_id = res.headers["X-Request-Id"]

    # Guard the fixture itself. Patching `docker_exec.exec` silently missed
    # every `from ... import exec` caller, and the test still passed because a
    # real docker call happened to get audited. An empty list here means the
    # interception stopped working, not that the app stopped calling docker.
    assert fake_exec, "fake_exec intercepted nothing - it is patching the wrong thing"

    rows = store.query(
        "SELECT kind, request_id, subject FROM audit_event WHERE request_id = ?",
        (request_id,),
    )
    kinds = {r["kind"] for r in rows}

    assert "container_exec" in kinds, "the container call was not audited"
    assert "request" in kinds, "the request itself was not audited"
    # Every row under this request shares its id - that is the whole point.
    assert all(r["request_id"] == request_id for r in rows)


def test_the_exec_row_records_what_actually_ran(app_home, fake_exec):
    """`docker_exec` is the ground-truth hook: it must record the command."""
    from app.core import store

    _client().get("/api/watcher")
    assert fake_exec, "fake_exec intercepted nothing"

    rows = store.query(
        "SELECT subject, detail_json FROM audit_event WHERE kind='container_exec'"
    )
    assert rows, "no container_exec row"
    detail = json.loads(rows[0]["detail_json"])
    assert "command" in detail and detail["command"]
    assert detail["returncode"] == 0
    # Shapes, not contents.
    assert "stdout_bytes" in detail


def test_a_failing_request_is_still_audited(app_home):
    from app.core import store

    res = _client().get("/api/nope")
    assert res.status_code == 404

    rows = store.query("SELECT status FROM audit_event WHERE kind='request'")
    assert rows and rows[0]["status"] == "error"
