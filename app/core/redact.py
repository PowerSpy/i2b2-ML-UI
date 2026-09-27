"""Small numbers, taken out before they are served.

One module, called at each serialisation point, rather than middleware.
Middleware sees a dict and cannot tell a confusion-matrix cell from a job id,
so it would have to guess - and the guess would be wrong in both directions.

## Three rules

**1. Suppressed is null, never zero.** A reader must not be able to tell "two
patients" from "no patients". Zero says the second, confidently and wrongly,
and it is the shape most such panels get wrong.

**2. Suppressed says so.** Every payload carries a `suppressed` list naming the
fields that were withheld, so a null is never ambiguous between "small",
"not applicable" and "not loaded yet". Those three look identical otherwise
and mean completely different things.

**3. Complementary suppression.** If one cell in a group is withheld, the whole
group goes, totals included. Hiding `tn` while publishing `tp`, `fp`, `fn` and
`n_samples` hides nothing: `tn = n_samples - tp - fp - fn`. This is the rule
that makes the difference between suppression and the appearance of it.

k is `settings.min_cell_size` (11), matching the CMS cell-size suppression
policy - a published rule to point a reviewer at rather than a number we
picked.

## What this module is not

It is not anonymity. A researcher who can run repeated builds over shifting
cohorts can reconstruct membership by differencing, and k-anonymity has no
answer to an adaptive querier. The audit log is the detection story there, not
this. See the residual risks in the README.
"""

from __future__ import annotations

from app.core.config import settings

MIN_CELL = settings.min_cell_size


def applies_to(principal) -> bool:
    """Whether cell-size suppression applies to this caller.

    Researchers, yes. Custodians, no - and that is a deliberate call rather
    than an oversight. A custodian loads the data, can delete it, and reaches
    the warehouse directly through this app's own loader; withholding a count
    of four orphan facts from the person whose job is to fix those four facts
    would make `/data-quality` useless for the only purpose it has, while
    protecting nothing they could not already read.

    Patient *identifiers* are a separate rule and are refused to researchers
    unconditionally, suppression or not.

    Fails closed: anything that does not declare a role is treated as a
    researcher, so a new principal type does not silently gain access.
    """
    return bool(getattr(principal, "is_researcher", True))


def small(n) -> bool:
    """Whether `n` is a count too small to publish. Zero is not small."""
    if n is None:
        return False
    try:
        value = float(n)
    except (TypeError, ValueError):
        return False
    return 0 < value < MIN_CELL


def count(n):
    """A count, or None when it would describe too few people."""
    return None if small(n) else n


def group(values: dict, *, totals: tuple[str, ...] = ()) -> tuple[dict, list[str]]:
    """Suppress a set of related counts together.

    Returns `(values, suppressed_field_names)`. If any member is small, **every**
    member goes, including the totals named in `totals` - because a total plus
    the surviving cells gives the withheld one back by subtraction.

    This is the rule worth the most care. Suppressing only the small cell looks
    like suppression, passes a casual review, and discloses the number anyway.
    """
    if not values:
        return {}, []

    offenders = sorted(k for k, v in values.items() if small(v))
    if not offenders:
        return dict(values), []

    # The returned dict holds exactly the keys that came in - a total named in
    # `totals` usually lives in a different part of the payload, and inventing
    # a key here would put a null somewhere the caller never had a field.
    # It is reported in `withheld` so the caller nulls it where it really is.
    return {k: None for k in values}, sorted(set(values) | set(totals))


def reason(fields: list[str]) -> str | None:
    if not fields:
        return None
    return (
        f"withheld: fewer than {MIN_CELL} patients. Related figures go with it, "
        "because a total and the remaining cells would give the withheld one "
        "back by subtraction."
    )


# --------------------------------------------------------------------------
# the confusion matrix
#
# The counts a model reports are the most obviously disclosive numbers in this
# app: on a small cohort a single false negative is one identifiable person.

CONFUSION = ("true_positive", "false_positive", "true_negative", "false_negative")
CONFUSION_TOTALS = ("n_pos", "n_neg", "n_samples")


def counts(values: dict) -> tuple[dict, list[str]]:
    """Confusion-matrix cells and their totals, suppressed as one group."""
    cells = {k: v for k, v in values.items() if k in CONFUSION}
    rest = {k: v for k, v in values.items() if k not in CONFUSION}

    redacted, withheld = group(cells, totals=CONFUSION_TOTALS)
    if withheld:
        for key in CONFUSION_TOTALS:
            if key in rest:
                rest[key] = None
        # Any other count in the payload is suppressed too. A rate plus a
        # published total reconstructs a cell just as well as the cell did.
        for key, value in list(rest.items()):
            if small(value):
                rest[key] = None
                withheld.append(key)

    return {**redacted, **rest}, sorted(set(withheld))


def plot_counts(values: dict) -> tuple[dict, list[str]]:
    """The counts drawn into the diagnostic plots.

    Same rule, different key names - these arrive as tp/fp/tn/fn. Worth noting
    that this redacts the *numbers*; the plot images themselves are rendered
    inside the container and a confusion-matrix PNG has the cells written on
    it. Suppressing here and serving the image would be theatre, so the caller
    withholds the images too.
    """
    return group(values, totals=())
