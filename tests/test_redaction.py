"""Small numbers do not reach a researcher.

The rule that matters most here is **complementary suppression**: hiding one
cell of a group while publishing the rest and a total hides nothing, because
the withheld cell is the total minus the others. That looks like suppression,
passes a casual review, and discloses the number anyway - so it gets the
sharpest tests in this file.
"""

import pytest

from app.core import redact

MIN = redact.MIN_CELL


class Researcher:
    is_researcher = True


class Custodian:
    is_researcher = False


# --------------------------------------------------------------------------
# who it applies to


def test_suppression_applies_to_researchers():
    assert redact.applies_to(Researcher()) is True


def test_custodians_see_raw_counts():
    """Deliberate. A custodian loads the data and can delete it; withholding a
    count of four orphan facts from the person whose job is to fix those four
    facts protects nothing and breaks the page."""
    assert redact.applies_to(Custodian()) is False


def test_an_unknown_principal_is_treated_as_a_researcher():
    """Fails closed, so a new principal type does not silently gain access."""
    assert redact.applies_to(object()) is True
    assert redact.applies_to(None) is True


# --------------------------------------------------------------------------
# the basic rule


def test_zero_is_not_small():
    """"No patients" is a publishable fact. "Two patients" is not, and the two
    must not be rendered identically."""
    assert redact.small(0) is False
    assert redact.count(0) == 0


def test_a_count_below_the_threshold_becomes_none_not_zero():
    assert redact.count(1) is None
    assert redact.count(MIN - 1) is None
    assert redact.count(MIN) == MIN


def test_none_stays_none_and_is_not_called_small():
    assert redact.small(None) is False
    assert redact.count(None) is None


def test_a_non_number_is_left_alone():
    """Group helpers run over dicts that also carry labels and flags."""
    assert redact.small("PROCESSING") is False
    assert redact.count("PROCESSING") == "PROCESSING"


# --------------------------------------------------------------------------
# complementary suppression - the rule worth the most care


def test_one_small_cell_takes_the_whole_group_with_it():
    values, withheld = redact.group(
        {"a": 100, "b": 200, "c": 3}, totals=("total",))

    assert values == {"a": None, "b": None, "c": None}
    assert "total" in withheld


def test_a_group_with_nothing_small_is_published_whole():
    values, withheld = redact.group({"a": 100, "b": 200}, totals=("total",))
    assert values == {"a": 100, "b": 200}
    assert withheld == []


def test_a_suppressed_confusion_cell_cannot_be_recovered_by_subtraction():
    """The specific arithmetic this rule exists to defeat:

        tn = n_samples - tp - fp - fn

    Publishing three cells and the total is publishing the fourth.
    """
    counts, withheld = redact.counts({
        "true_positive": 40, "false_positive": 12,
        "true_negative": 3, "false_negative": 15,     # one small cell
        "n_pos": 55, "n_neg": 15, "n_samples": 70,
    })

    for key in ("true_positive", "false_positive", "true_negative",
                "false_negative", "n_pos", "n_neg", "n_samples"):
        assert counts[key] is None, f"{key} survived and gives the cell back"
    assert "n_samples" in withheld


def test_a_healthy_confusion_matrix_is_published_intact():
    counts, withheld = redact.counts({
        "true_positive": 40, "false_positive": 12,
        "true_negative": 30, "false_negative": 15,
        "n_pos": 55, "n_neg": 42, "n_samples": 97,
    })

    assert withheld == []
    assert counts["true_negative"] == 30
    assert counts["n_samples"] == 97


def test_every_small_count_in_the_payload_goes_not_only_the_cells():
    """A rate beside a published total reconstructs a cell just as well as the
    cell did."""
    counts, _ = redact.counts({
        "true_positive": 2, "false_positive": 100,
        "true_negative": 100, "false_negative": 100,
        "n_samples": 302, "some_other_count": 4,
    })
    assert counts["some_other_count"] is None


def test_the_reason_names_the_threshold_and_the_arithmetic():
    """A null has to be unambiguous between "small", "not applicable" and
    "not loaded yet" - those look identical and mean different things."""
    note = redact.reason(["true_negative"])
    assert str(MIN) in note
    assert "subtraction" in note
    assert redact.reason([]) is None


# --------------------------------------------------------------------------
# no small count survives anywhere in a payload


def sweep(node, path="$"):
    """Every integer in a payload, with the path that produced it."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            found += sweep(v, f"{path}.{k}")
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            found += sweep(v, f"{path}[{i}]")
    elif isinstance(node, int) and not isinstance(node, bool):
        found.append((path, node))
    return found


def test_nothing_below_the_threshold_survives_a_full_metrics_payload():
    """A recursive sweep rather than per-field assertions, so a field added
    later is covered without anyone remembering this file."""
    counts, withheld = redact.counts({
        "true_positive": 2, "false_positive": 9, "true_negative": 300,
        "false_negative": 1, "n_pos": 3, "n_neg": 309, "n_samples": 312,
    })
    payload = {"counts": counts, "suppressed": withheld,
               "headline": {"roc_auc": 0.81}}

    small = [(p, n) for p, n in sweep(payload) if 0 < n < MIN]
    assert not small, f"counts below {MIN} reached the payload: {small}"


# --------------------------------------------------------------------------
# job output


def test_an_etl_traceback_is_withheld_from_a_researcher():
    """The least obvious surface in the app: `error_stack` carries the failing
    SQL and, on a bad row, the row - and the UI polls it every ten seconds."""
    from app.api.jobs import Job, _redact_job

    job = _redact_job(Job(
        id=1, status="ERROR",
        error_stack="Traceback...\npsycopg2.errors: INSERT INTO observation_fact "
                    "(patient_num) VALUES (1001234)"))

    assert "1001234" not in (job.error_stack or "")
    assert "observation_fact" not in (job.error_stack or "")
    assert job.suppressed == ["error_stack"]
    assert job.suppression_note


def test_a_transform_failure_reaches_the_person_who_caused_it():
    """The one exception, and the reason for it: this message is written by
    this application about the researcher's own code. Withholding it would
    leave them unable to debug the one thing they are responsible for."""
    from app.api.jobs import Job, _redact_job

    job = _redact_job(Job(
        id=2, status="ERROR",
        error_stack="Traceback...\n"
                    "RuntimeError: TRANSFORM FAILED: the transform returned None\n"
                    "  at psycopg2 internals with SELECT * FROM observation_fact"))

    assert "TRANSFORM FAILED" in job.error_stack
    assert "returned None" in job.error_stack
    # Only the sentence this app wrote, not the container's surroundings.
    assert "observation_fact" not in job.error_stack


def test_a_job_with_no_output_gains_no_suppression_notice():
    """A notice on a job that simply said nothing would be noise, and would
    teach people to ignore the notice that matters."""
    from app.api.jobs import Job, _redact_job

    job = _redact_job(Job(id=3, status="COMPLETED"))
    assert job.suppressed == []
    assert job.suppression_note is None
