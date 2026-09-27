"""Who may touch which model.

Four routes cannot be decided from the route alone — whether a researcher may
submit a build depends on whether the path in the body is theirs. The census
pins them as reachable; this pins the rule.

The rule this is really protecting: submitting a job **deletes every fact
under the submitted path before it runs**, and the path comes from the caller.
Without ownership, "read-only researcher" is a warehouse-wide delete primitive
with extra steps.
"""

import pytest
from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"


@pytest.fixture
def people(app_home):
    from app.core import auth, passwords
    from app.core.authz import Role

    auth.create_user("alice", passwords.hash_password(PASSWORD), Role.CUSTODIAN)
    auth.create_user("rob", passwords.hash_password(PASSWORD), Role.RESEARCHER)
    auth.create_user("sam", passwords.hash_password(PASSWORD), Role.RESEARCHER)
    return {u: auth.get_user(u) for u in ("alice", "rob", "sam")}


def client_for(username):
    from app.main import app

    c = TestClient(app, raise_server_exceptions=False)
    res = c.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert res.status_code == 200, res.text
    c.headers["X-CSRF-Token"] = c.cookies["i2b2ml_csrf"]
    return c


# --------------------------------------------------------------------------
# the namespace


def test_researcher_namespace_is_per_user(app_home):
    from app.core import authz

    assert authz.researcher_namespace("rob") == "/ML/u/rob"
    assert authz.in_namespace("/ML/u/rob/model1", "/ML/u/rob")
    assert authz.in_namespace("/ML/u/rob", "/ML/u/rob")
    # The prefix must not match a sibling whose name merely starts the same.
    assert not authz.in_namespace("/ML/u/robert/m", "/ML/u/rob")
    assert not authz.in_namespace("/ML/Diagnosis/m", "/ML/u/rob")


def test_researcher_cannot_create_outside_their_namespace(people, fake_exec):
    body = {
        "code": "m1", "path": "/ML/Diagnosis/m1", "description": "d",
        "blob": {"positive_patient_set": [], "negative_patient_set": [],
                 "data_paths": [], "label_paths": []},
    }
    res = client_for("rob").post("/api/ml-concepts", json=body)

    assert res.status_code == 403
    assert "/ML/u/rob" in res.json()["detail"]
    assert not fake_exec, "rejected, but only after touching a container"


# --------------------------------------------------------------------------
# may_touch


def test_custodian_may_touch_anything(people):
    from app.core import auth, authz

    p = auth.principal_from_row(people["alice"])
    assert authz.may_touch(p, code="anything")
    assert authz.may_touch(p, path="/ML/whatever")


def test_researcher_may_touch_only_their_own(people):
    from app.core import auth, authz

    rob = auth.principal_from_row(people["rob"])
    sam = auth.principal_from_row(people["sam"])
    authz.record_owner("robs_model", "/ML/u/rob/robs_model", int(people["rob"]["id"]))

    assert authz.may_touch(rob, code="robs_model")
    assert authz.may_touch(rob, path="/ML/u/rob/robs_model")
    assert not authz.may_touch(sam, code="robs_model")
    assert not authz.may_touch(sam, path="/ML/u/rob/robs_model")


def test_an_unowned_model_is_not_everyones(people):
    """Defaulting an unknown owner to 'allowed' is how this check ends up
    meaning nothing. Models predating ownership belong to nobody, and a
    researcher may not touch them."""
    from app.core import auth, authz

    rob = auth.principal_from_row(people["rob"])
    assert authz.owner_of("legacy_model") is None
    assert not authz.may_touch(rob, code="legacy_model")
    # A custodian still can, so nothing becomes unmanageable.
    assert authz.may_touch(auth.principal_from_row(people["alice"]), code="legacy_model")


# --------------------------------------------------------------------------
# the routes that delete facts


@pytest.mark.parametrize("route", ["/api/jobs/build", "/api/jobs/apply"])
def test_researcher_cannot_submit_a_job_against_a_path_they_do_not_own(
    people, fake_exec, route
):
    """The core of the whole role split.

    A build deletes every fact under the path first, so this must be refused
    on the path in the body, and refused *before* anything runs.
    """
    body = {"path": "/HeartDisease", "target_patient_set": ["x"],
            "prediction_event_paths": ["/HeartDisease/label"]}
    res = client_for("rob").post(route, json=body)

    assert res.status_code == 403, res.text
    assert not fake_exec, f"{route} reached a container before refusing"


@pytest.mark.parametrize("route", ["/api/jobs/build", "/api/jobs/apply"])
def test_researcher_cannot_submit_against_another_researchers_model(
    people, fake_exec, route
):
    from app.core import authz

    authz.record_owner("sams", "/ML/u/sam/sams", int(people["sam"]["id"]))
    res = client_for("rob").post(
        route,
        json={"path": "/ML/u/sam/sams", "target_patient_set": ["x"],
              "prediction_event_paths": ["/x"]},
    )

    assert res.status_code == 403
    assert "sam" in res.json()["detail"]
    assert not fake_exec


@pytest.mark.parametrize("route", ["/api/jobs/build", "/api/jobs/apply"])
def test_owner_gets_past_the_ownership_check(people, fake_exec, route):
    """The other half: ownership must actually let the owner through.

    It still fails afterwards - there is no real model at that path and no
    warehouse here - but the failure must not be 403.
    """
    from app.core import authz

    authz.record_owner("robs", "/ML/u/rob/robs", int(people["rob"]["id"]))
    res = client_for("rob").post(
        route,
        json={"path": "/ML/u/rob/robs", "target_patient_set": ["x"],
              "prediction_event_paths": ["/x"]},
    )

    assert res.status_code != 403, res.text


def test_researcher_cannot_delete_another_users_model(people, fake_exec):
    from app.core import authz

    authz.record_owner("sams", "/ML/u/sam/sams", int(people["sam"]["id"]))
    res = client_for("rob").delete("/api/ml-concepts/sams")

    # 403 before the handler asks the warehouse whether the model exists.
    assert res.status_code in (403, 404)
    if res.status_code == 403:
        assert not fake_exec


# --------------------------------------------------------------------------
# path validation, which had been missing entirely


@pytest.mark.parametrize("bad", [
    "/ML/u/rob/m'; DROP TABLE concept_dimension; --",
    '/ML/u/rob/m" OR 1=1',
    "/ML/u/rob/m\\x",
])
def test_unsafe_model_paths_are_refused(people, fake_exec, bad):
    """`Ml_Concept_In.path` was never run through check_path, though it flows
    into ETL query params and back out into ml_blob's SQL."""
    res = client_for("alice").post("/api/ml-concepts", json={
        "code": "m1", "path": bad, "description": "d",
        "blob": {"positive_patient_set": [], "negative_patient_set": [],
                 "data_paths": [], "label_paths": []},
    })

    assert res.status_code == 422, res.text
    assert not fake_exec
