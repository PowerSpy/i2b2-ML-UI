"""The audit log must never contain what it is auditing.

An audit trail that leaks the data it records is worse than none: it turns a
controlled read into a permanent plaintext copy on disk, outside every check
the API applies. These tests drive sentinel values through the sinks and assert
they do not come out the other side.

The denylist in `app/core/audit.py` is name-based and therefore crude. Crude is
the point - it fails safe, and a false positive costs a field in a log rather
than a disclosure. These tests are what stop it silently decaying when someone
adds a new `audit.event()` call with an innocent-looking keyword.
"""

import json

from conftest import audit_text

# Distinctive enough that a substring match cannot be a coincidence.
PATIENT = "PATIENT-SENTINEL-88311"
SECRET = "SECRET-SENTINEL-c0ffee"
BLOB = "BLOB-SENTINEL-deadbeef"


def test_denied_keys_are_redacted(app_home):
    from app.core import audit

    audit.event(
        "probe",
        password=SECRET,
        session_id=SECRET,
        authorization=SECRET,
        etl_password=SECRET,
        concept_blob=BLOB,
        patient_num=PATIENT,
        patients=[PATIENT, PATIENT],
        mrn=PATIENT,
        tval_char=PATIENT,
    )

    text = audit_text(app_home)
    assert text, "the audit sinks wrote nothing at all"
    for sentinel in (PATIENT, SECRET, BLOB):
        assert sentinel not in text, f"{sentinel} reached the audit log"
    assert "[redacted]" in text


def test_counts_survive_the_denylist(app_home):
    """Shapes are the point of this log; redacting them makes it useless.

    An earlier substring-only denylist matched "rows" inside `rows_loaded` and
    redacted it on every load — the single number that says whether the load
    did anything. These are the count fields the real hooks emit, and they must
    come through intact.
    """
    from app.core import audit

    audit.event(
        "probe",
        rows_loaded=41,
        rows_removed=7,
        rows_before=100,
        rows_after=59,
        row_count=12,
        rows_returned=3,
        total_available=99,
        patients_with_value=25,
        stdout_bytes=512,
        returncode=0,
    )

    text = audit_text(app_home)
    for expected in ("41", "\"rows_removed\": 7", "\"row_count\": 12",
                     "\"patients_with_value\": 25", "\"stdout_bytes\": 512"):
        assert expected in text, f"{expected} was lost from the audit log"
    assert "[redacted]" not in text


def test_bare_container_names_are_still_denied(app_home):
    """The other half: standing alone, these name data rather than a count."""
    from app.core import audit

    audit.event("probe", rows="a,b,c", values="1,2,3", data=PATIENT, csv=PATIENT)

    text = audit_text(app_home)
    assert PATIENT not in text
    assert "a,b,c" not in text
    assert text.count("[redacted]") >= 4


def test_collections_are_summarised_not_enumerated(app_home):
    """A list is the shape patient identifiers arrive in."""
    from app.core import audit

    audit.event("probe", harmless_list=[PATIENT, PATIENT, PATIENT])

    text = audit_text(app_home)
    assert PATIENT not in text
    assert "3 items" in text


def test_long_text_is_bounded(app_home):
    from app.core import audit

    audit.event("probe", command="x" * 20_000)

    text = audit_text(app_home)
    # Kept, but bounded - the point is to identify what ran, not to store it.
    assert "chars)" in text
    assert "x" * 20_000 not in text


def test_nested_denied_keys_are_caught(app_home):
    """Scrubbing is recursive; a nested dict is the obvious way to slip past."""
    from app.core import audit

    audit.event("probe", detail={"inner": {"password": SECRET, "ok": "visible"}})

    text = audit_text(app_home)
    assert SECRET not in text
    assert "visible" in text


def test_event_never_raises_when_a_sink_fails(app_home, monkeypatch, capsys):
    """A broken audit sink must not turn a working request into a 500.

    It must also not fail silently - a dead audit log that nobody notices is
    the failure mode this whole module exists to avoid.
    """
    from app.core import audit

    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(audit.store, "write", boom)
    monkeypatch.setattr(audit, "_to_jsonl", boom)

    audit.event("probe", note="still fine")  # must not raise

    assert "[audit]" in capsys.readouterr().err


def test_both_sinks_receive_the_same_event(app_home):
    from app.core import audit, store

    audit.event("probe", subject="thing", note="value-kept")

    rows = store.query("SELECT kind, subject, detail_json FROM audit_event")
    assert [r["kind"] for r in rows] == ["probe"]
    assert rows[0]["subject"] == "thing"
    assert json.loads(rows[0]["detail_json"])["note"] == "value-kept"

    jsonl = (app_home / "audit").glob("*.jsonl")
    lines = [json.loads(ln) for f in jsonl for ln in f.read_text(encoding="utf8").splitlines()]
    assert len(lines) == 1
    assert lines[0]["kind"] == "probe"
    assert lines[0]["detail"]["note"] == "value-kept"


def test_build_stamp_is_on_every_row(app_home):
    """Without it a log line cannot be tied to the code that produced it."""
    from app.core import audit, buildinfo, store

    audit.event("probe")

    row = store.query("SELECT app_version, git_sha FROM audit_event")[0]
    assert row["app_version"] == buildinfo.VERSION
    assert row["git_sha"] == buildinfo.git_sha()


def test_actor_is_anonymous_before_auth_exists(app_home):
    """Honest default. There is no authentication yet, and the log says so."""
    from app.core import audit, store

    audit.event("probe")

    assert store.query("SELECT actor_username FROM audit_event")[0]["actor_username"] == "anonymous"
