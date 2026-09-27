"""The container line, and how an exit code becomes a sentence.

Neither needs a daemon. The `docker run` flags are the actual security
boundary, so they are asserted rather than trusted to a code review, and the
exit-code reading is where an out-of-memory kill gets told apart from a
timeout - which is worth a test because both are exit 137 and reporting one as
the other sends a researcher to fix the wrong thing.

**This file does not prove the flags work.** It proves they are passed. That
they do what they say needs a reachable daemon and the escape attempts listed
in the plan.
"""

import subprocess

import pytest

from app.core import sandbox


def args():
    return sandbox.docker_args("i2b2ml-sandbox-test", 60)


def flag(name):
    a = args()
    return [a[i + 1] for i, v in enumerate(a) if v == name]


# --------------------------------------------------------------------------
# the boundary


def test_the_network_is_off():
    """This is the security control. Everything else on the line is hygiene."""
    assert flag("--network") == ["none"]


def test_it_does_not_run_as_root():
    assert flag("--user") == ["65534:65534"]


def test_the_filesystem_is_read_only_with_a_noexec_scratch():
    a = args()
    assert "--read-only" in a
    tmpfs = flag("--tmpfs")[0]
    assert tmpfs.startswith("/tmp:")
    # So a transform that writes a file cannot then run it.
    assert "noexec" in tmpfs and "nosuid" in tmpfs


def test_capabilities_are_dropped_and_cannot_be_regained():
    assert flag("--cap-drop") == ["ALL"]
    assert flag("--security-opt") == ["no-new-privileges"]


def test_swap_is_disabled_along_with_the_memory_cap():
    """`--memory` without `--memory-swap` lets an over-allocating transform
    thrash instead of dying, and it then trips the wall clock - reported as a
    timeout, which is the wrong diagnosis and sends the researcher to optimise
    code that is not slow."""
    assert flag("--memory") == flag("--memory-swap") == ["2g"]


def test_cpu_and_process_count_are_bounded():
    assert flag("--cpus") == ["1.0"]
    assert flag("--pids-limit") == ["128"]


def test_nothing_the_transform_prints_reaches_the_host_log_driver():
    assert flag("--log-driver") == ["none"]


def test_the_container_is_named_and_not_auto_removed():
    """Deliberately not `--rm`. `OOMKilled` is the only way to tell an
    out-of-memory kill from a timeout kill, and an auto-removed container is
    gone before it can be inspected."""
    a = args()
    assert "--rm" not in a
    assert flag("--name") == ["i2b2ml-sandbox-test"]


def test_no_mount_of_any_kind():
    """A host mount would be an egress channel, and a docker socket mount
    would make the whole sandbox decorative."""
    a = args()
    for forbidden in ("-v", "--volume", "--mount"):
        assert forbidden not in a
    assert not any("docker.sock" in str(x) for x in a)


def test_no_credential_reaches_the_container():
    """Swept from the settings rather than listed, so a credential added later
    is covered without anyone remembering this file exists."""
    from app.core.config import Settings, settings

    joined = " ".join(args())
    checked = []
    for name in Settings.model_fields:
        # Usernames deliberately excluded: `db_user` is "i2b2", which is a
        # substring of the image name, and a username is not the secret.
        if not any(w in name for w in ("password", "secret", "token",
                                       "credential", "key")):
            continue
        value = getattr(settings, name, None)
        if isinstance(value, str) and len(value) >= 3:
            checked.append(name)
            assert value not in joined, f"{name} reached the container line"

    assert checked, "no credential fields were found to check"


def test_the_image_is_the_configured_one_and_comes_last():
    a = args()
    assert a[-1] == sandbox.IMAGE
    assert a[:2] == ["docker", "run"]


def test_the_host_never_learns_to_build_a_dataframe():
    """Nothing in `app/` may import pandas or numpy.

    The host process holds the container credentials, and its only job with a
    frame is to describe it in aggregate. It is also the reason the generator
    emits a *plan* rather than a frame: if the host could materialise one, the
    temptation to do it there - with a different pandas than the real build -
    would eventually be taken, and "it worked in dev" would stop meaning
    anything.

    Cheap to keep true now and expensive to restore once it is false.
    """
    import ast
    from pathlib import Path

    app = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in app.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for n in names:
                if n.split(".")[0] in ("pandas", "numpy", "sklearn", "scipy"):
                    offenders.append(f"{path.name}:{node.lineno} imports {n}")

    assert not offenders, "\n".join(offenders)


# --------------------------------------------------------------------------
# turning an exit into a sentence


def interpret(code=0, stdout="", stderr="", timed_out=False, oom=False):
    return sandbox._interpret(code, stdout, stderr, timed_out=timed_out,
                              oom=oom, timeout_s=60)


def test_out_of_memory_is_reported_as_memory_not_as_a_timeout():
    """A transform that allocates too much also runs long, so both signals
    fire. `OOMKilled` wins."""
    r = interpret(code=137, timed_out=True, oom=True)

    assert r["error"]["kind"] == "memory"
    assert "memory" in r["error"]["message"]
    assert "second" not in r["error"]["message"]


def test_a_wall_clock_kill_is_reported_as_a_timeout():
    r = interpret(code=137, timed_out=True, oom=False)

    assert r["error"]["kind"] == "timeout"
    assert "60 seconds" in r["error"]["message"]


def test_an_empty_response_is_a_crash_and_says_so():
    r = interpret(code=1, stdout="", stderr="Traceback ...")

    assert r["error"]["kind"] == "crashed"
    assert "exited with code 1" in r["error"]["message"]
    assert "Traceback" in r["container_stderr"]


def test_unparseable_output_blames_the_runner_not_the_researcher():
    """`run.py` takes fd 1 away from user code precisely so a `print` cannot
    cause this. If it happens anyway it is a runner bug, and saying so stops
    someone hunting for a stray print that is not there."""
    r = interpret(code=0, stdout="{not json")

    assert r["error"]["kind"] == "crashed"
    assert "bug in the sandbox runner" in r["error"]["message"]


def test_an_oversized_response_is_refused_rather_than_parsed():
    r = interpret(code=0, stdout="x" * (sandbox.MAX_RESPONSE_BYTES + 1))
    assert r["error"]["kind"] == "crashed"


def test_a_good_response_passes_through_with_stderr_attached():
    r = interpret(code=0, stdout='{"ok": true, "report": {"changed": true}}',
                  stderr="a warning from a library")

    assert r["ok"] is True
    assert r["report"]["changed"] is True
    assert "a warning" in r["container_stderr"]


def test_a_response_claiming_nothing_is_treated_as_a_failure():
    """Absent `ok` defaults closed. The alternative is a malformed response
    reading as a success."""
    assert interpret(code=0, stdout='{"report": {}}')["ok"] is False


# --------------------------------------------------------------------------
# refusing before running


def test_a_missing_daemon_names_the_fix_rather_than_raising(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=20)

    monkeypatch.setattr(subprocess, "run", boom)
    ok, why = sandbox.available()

    assert ok is False
    assert "not running" in why


def test_a_missing_image_names_the_build_command(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0] if a else [], 1, "", "Error: No such image"))
    ok, why = sandbox.available()

    assert ok is False
    assert "build.sh" in why and "probe" in why


def test_run_transform_refuses_instead_of_launching_when_unavailable(monkeypatch):
    monkeypatch.setattr(sandbox, "available", lambda: (False, "no docker here"))
    launched = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: launched.append(a) or None)

    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.run_transform("def transform(df): return df", {"n_rows": 10})

    assert not launched, "a container was started after the check failed"
