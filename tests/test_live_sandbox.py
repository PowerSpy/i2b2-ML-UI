"""The sandbox isolation, proved by trying to break it.

`test_sandbox_args.py` asserts the flags are *passed*. This asserts they
*work*, which is a different claim and the one that matters. Each test tries a
specific escape and requires the right refusal - not just any failure, because
"it errored" is satisfied by a typo.

Needs the image. Build it with `./sandbox/build.sh probe && ./sandbox/build.sh`.
Skips cleanly without it; a green run that skipped these has proved nothing
about the boundary.

Each case starts a container, so this file is slow by construction - roughly
ten seconds a test. That is the cost of testing the real thing.
"""

import pytest

pytestmark = pytest.mark.live

PLAN_DOC = {
    "scope": "live-sandbox", "note": "", "min_cell": 11,
    "patients_in_scope": 60, "basis": "",
    "columns": [{
        "code": "age", "name": "Age", "kind": "numeric", "fill_rate": 1.0,
        "patients_with_value": 60, "integer_like": True, "suppressed": [],
        "low": 29.0, "p05": 35.0, "p25": 48.0, "p50": 56.0, "p75": 61.0,
        "p95": 68.0, "high": 71.0,
    }],
}


@pytest.fixture(scope="module")
def box():
    from app.core import sandbox

    ok, why = sandbox.available()
    if not ok:
        pytest.skip(f"sandbox unavailable: {why}")
    return sandbox


@pytest.fixture(scope="module")
def plan():
    from app.core import synthetic

    return synthetic.plan(PLAN_DOC, n_rows=60, seed=3)


def run(box, plan, source, timeout_s=45):
    return box.run_transform(source, plan, timeout_s=timeout_s)


# --------------------------------------------------------------------------
# it works at all


def test_a_transform_runs_end_to_end(box, plan):
    r = run(box, plan, "def transform(df):\n    return df.assign(x=df['age']*2)\n")

    assert r["ok"], r["error"]
    assert r["report"]["columns_added"] == ["x"]
    assert r["preview"]["rows"]


# --------------------------------------------------------------------------
# the boundary


def test_the_network_is_unreachable_through_a_library_the_guard_allows(box, plan):
    """The important one. `pandas.read_csv` opens the socket, so the import
    allowlist never sees it - which is precisely why the allowlist is
    documented as ergonomics and `--network none` as the control.

    If this ever passes, the sandbox is not a sandbox.
    """
    r = run(box, plan,
            "import pandas as pd\n"
            "def transform(df):\n"
            "    pd.read_csv('http://i2b2-pg:5432/')\n"
            "    return df\n")

    assert not r["ok"]
    assert r["error"]["kind"] == "raised"
    blob = r["error"]["message"].lower()
    assert "name resolution" in blob or "urlerror" in blob or "connection" in blob


def test_the_warehouse_port_is_unreachable_by_address(box, plan):
    """Not just DNS. A hardcoded address must fail too, or `--network none`
    would only be stopping name lookups."""
    r = run(box, plan,
            "import pandas as pd\n"
            "def transform(df):\n"
            "    pd.read_csv('http://127.0.0.1:5432/')\n"
            "    return df\n")
    assert not r["ok"]


def test_the_etl_containers_files_are_not_present(box, plan):
    """No host mounts. If this file were readable the sandbox would be sharing
    a filesystem with the thing holding the database credentials."""
    r = run(box, plan,
            "import pandas as pd\n"
            "def transform(df):\n"
            "    pd.read_csv('/usr/src/app/requirements.txt')\n"
            "    return df\n")

    assert not r["ok"]
    assert "No such file" in r["error"]["message"]


def test_the_root_filesystem_is_read_only(box, plan):
    r = run(box, plan,
            "def transform(df):\n"
            "    df.to_csv('/leak.csv')\n"
            "    return df\n")

    assert not r["ok"]
    assert "Read-only file system" in r["error"]["message"]


def test_no_environment_variable_carries_a_credential(box, plan):
    """The transform can read its own environment. Nothing in it may be
    useful."""
    r = run(box, plan,
            "def transform(df):\n"
            "    import os\n"
            "    return df\n")
    # `import os` is refused by the guard, which is the ergonomic layer. The
    # substantive check is that the host never puts a secret on the command
    # line - see test_sandbox_args.test_no_credential_reaches_the_container.
    assert not r["ok"]
    assert r["error"]["kind"] == "rejected"


# --------------------------------------------------------------------------
# the two kills that are both exit 137


def test_an_over_allocating_transform_says_memory_and_not_timeout(box, plan):
    """A transform that allocates too much also runs long, so both signals
    fire. Reporting this as a timeout sends someone to optimise code that is
    not slow."""
    r = run(box, plan, "def transform(df):\n    x = [0] * 10**9\n    return df\n")

    assert not r["ok"]
    assert r["error"]["kind"] == "memory", r["error"]
    assert "memory" in r["error"]["message"].lower()


def test_a_spinning_transform_says_timeout_and_not_memory(box, plan):
    """And the converse, which is the one that would be wrong if the container
    were allowed to swap."""
    r = run(box, plan,
            "def transform(df):\n    while True:\n        pass\n", timeout_s=8)

    assert not r["ok"]
    assert r["error"]["kind"] == "timeout", r["error"]
    assert "8 seconds" in r["error"]["message"]


def test_the_deadline_is_enforced_inside_the_container(box, plan):
    """Not only by the host's outer limit. Without the in-container alarm an
    8-second budget took 30 seconds to report, because the host has to allow
    for container startup on top of it."""
    r = run(box, plan,
            "def transform(df):\n    while True:\n        pass\n", timeout_s=5)

    assert r["error"]["kind"] == "timeout"
    assert r["duration_ms"] < (5 + sandbox_overhead()) * 1000


def sandbox_overhead():
    from app.core import sandbox

    return sandbox.OVERHEAD_S


# --------------------------------------------------------------------------
# no container is left behind


def test_containers_are_removed_even_when_the_transform_is_killed(box, plan):
    """`--rm` is not used, so nothing else deletes them. A leak of one
    container per dry run would be invisible until the disk filled."""
    import subprocess

    def sandbox_containers():
        p = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "name=i2b2ml-sandbox-"],
            capture_output=True, text=True, timeout=30)
        return [x for x in p.stdout.split() if x]

    before = set(sandbox_containers())
    run(box, plan, "def transform(df):\n    while True:\n        pass\n", timeout_s=5)
    run(box, plan, "def transform(df):\n    return df.assign(x=1.0)\n")

    assert not (set(sandbox_containers()) - before), "a sandbox container leaked"


# --------------------------------------------------------------------------
# the version match, against the interpreter that really runs the build


def _versions(argv, timeout=120):
    import json
    import subprocess

    probe = (
        "import importlib.metadata as m, json;"
        "print(json.dumps({p: m.version(p) for p in "
        "('pandas','numpy','scikit-learn','scipy')}))"
    )
    p = subprocess.run(argv + [probe], capture_output=True, text=True,
                       timeout=timeout)
    if p.returncode != 0:
        pytest.skip(f"probe failed: {(p.stderr or '').strip()[:150]}")
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_the_sandbox_matches_the_interpreter_that_trains_the_model(box):
    """The dev loop's whole promise, asserted end to end.

    The container is started with `source /usr/src/app/.venv/bin/activate`, so
    the venv is what trains the model - **not** the system python3, which has
    none of these libraries. A probe pointed at python3 reported every package
    missing, then, once that was handled, reported a version match that did not
    exist: requirements.txt declares pandas==2.3.0 and the venv runs 2.3.3.

    Comparing the two directly cannot be fooled by either mistake.
    """
    from app.core.config import settings

    etl = _versions(["docker", "exec", settings.container,
                     "/usr/src/app/.venv/bin/python", "-c"])
    sand = _versions(["docker", "run", "--rm", "--entrypoint", "python",
                      box.IMAGE, "-c"])

    assert sand == etl, (
        f"sandbox {sand} does not match the ETL venv {etl}. Re-run "
        "./sandbox/build.sh probe && ./sandbox/build.sh")


def test_the_declared_requirements_are_not_trusted_as_the_pin():
    """`/usr/src/app/requirements.txt` has drifted from the venv. Pinning to it
    would look right and be wrong, which is why build.sh probes the installed
    versions and records whether it managed to."""
    import subprocess

    from app.core.config import settings

    p = subprocess.run(
        ["docker", "exec", settings.container, "sh", "-c",
         "grep -iE '^(pandas|imbalanced-learn|xgboost)==' /usr/src/app/requirements.txt"],
        capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        pytest.skip("no requirements.txt in the container")

    declared = dict(line.split("==") for line in p.stdout.split())
    installed = _versions(["docker", "exec", settings.container,
                           "/usr/src/app/.venv/bin/python", "-c"])

    # Not an assertion that they differ - that would break when someone fixes
    # the container. An assertion that the pin followed the *installed* one.
    from pathlib import Path
    req = Path(__file__).resolve().parents[1] / "sandbox" / "requirements.txt"
    pinned = dict(
        line.split("==") for line in req.read_text().split()
        if "==" in line and not line.startswith("#"))

    assert pinned["pandas"] == installed["pandas"], (
        f"pinned {pinned['pandas']}, venv has {installed['pandas']}, "
        f"requirements.txt declares {declared.get('pandas')}")
