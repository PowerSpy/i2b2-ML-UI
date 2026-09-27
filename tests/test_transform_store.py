"""Encoding a transform so the blob cannot mangle it.

The round trip against a real ETL lives in `test_live_warehouse.py`; a mock
would pass here while the real thing corrupts, because the corruption happens
container-side. These cover the half that is pure logic.
"""

import base64
import hashlib

import pytest

from app.core import transform_store as ts

SRC = "def transform(df):\n    # it's a comment\n    return df\n"


# --------------------------------------------------------------------------
# the reason base64 is not optional


def test_the_encoded_payload_contains_no_quote_or_backslash():
    """The blob is repaired by an unconditional `blob.replace("'", '"')` before
    `json.loads`. Any quote or backslash in a stored value is rewritten by that
    swap, and a transform is nothing but quotes and backslashes."""
    packed = ts.encode(SRC)[ts.SOURCE]

    for ch in ("'", '"', "\\", "\n", "\r"):
        assert ch not in packed


def test_a_quote_swap_leaves_the_payload_untouched():
    """The exact transformation the container applies, asserted directly."""
    packed = ts.encode(SRC)[ts.SOURCE]
    assert packed.replace("'", '"') == packed


@pytest.mark.parametrize("source", [
    "def transform(df):\n    # it's mine\n    return df\n",
    'def transform(df):\n    x = "double"\n    return df\n',
    "def transform(df):\n    p = 'C:\\\\Users\\\\x'\n    return df\n",
    "def transform(df):\n    s = 'na\u00efve \u00b5g/dL \u2014 caf\u00e9'\n    return df\n",
    "def transform(df):\n\treturn df\n",
    "def transform(df):\r\n    return df\r\n",
])
def test_hostile_sources_survive_a_local_round_trip(source):
    blob = ts.encode(source)
    assert ts.decode(blob)["source"] == source


# --------------------------------------------------------------------------
# the digest


def test_the_digest_is_over_the_source_not_the_envelope():
    """Hashing the base64 would verify the packaging and not the payload."""
    blob = ts.encode(SRC)
    assert blob[ts.SHA] == hashlib.sha256(SRC.encode()).hexdigest()


def test_a_tampered_payload_is_reported_rather_than_returned_quietly():
    blob = ts.encode(SRC)
    blob[ts.SOURCE] = base64.b64encode(b"def transform(df):\n    return None\n").decode()

    record = ts.decode(blob)
    assert record["intact"] is False
    assert "does not match" in record["problem"]
    # Still returned, so it can be looked at and replaced.
    assert "return None" in record["source"]


def test_an_undecodable_payload_does_not_raise():
    """The model page has to render so the researcher can clear the damage."""
    record = ts.decode({ts.SOURCE: "not valid base64!!", ts.SHA: "x" * 64})

    assert record["intact"] is False
    assert record["source"] is None
    assert "not recoverable" in record["problem"]


def test_no_transform_reads_as_none_not_as_empty():
    assert ts.decode({}) is None
    assert ts.decode({ts.SOURCE: ""}) is None
    assert ts.decode(None) is None


# --------------------------------------------------------------------------
# bounds


def test_an_oversized_transform_is_refused_with_the_reason():
    """The blob travels as a URL query parameter on the update path. Measured
    on this ETL: 32 KB of source is accepted, 64 KB returns HTTP 414."""
    with pytest.raises(ts.TransformError) as e:
        ts.encode("x" * (ts.MAX_SOURCE_BYTES + 1))

    assert "travels in a URL" in str(e.value)


def test_the_limit_leaves_room_for_the_rest_of_the_blob():
    """Base64 inflates by 4/3, and the model config shares the same URL."""
    assert ts.MAX_SOURCE_BYTES * 4 / 3 < 44 * 1024


def test_an_empty_transform_is_refused():
    with pytest.raises(ts.TransformError):
        ts.encode("   \n\n  ")


def test_a_null_byte_is_refused():
    with pytest.raises(ts.TransformError):
        ts.encode("def transform(df):\n    return df\n\x00")


# --------------------------------------------------------------------------
# the carry-forward


def test_a_config_save_cannot_drop_a_transform():
    """ModelForm builds its blob from scratch and the backend writes it whole.
    Without this, changing the algorithm silently deletes the transform and the
    next build trains a different model and reports success."""
    existing = ts.encode(SRC, author="alice")
    existing["model_type"] = "logistic"

    fresh = {"model_type": "random_forest", "data_paths": ["/x"]}
    merged = ts.carry_forward(fresh, existing)

    assert merged["model_type"] == "random_forest"       # the edit lands
    assert ts.decode(merged)["source"] == SRC            # the transform stays
    assert merged[ts.AUTHOR] == "alice"


def test_carry_forward_does_not_resurrect_a_deleted_transform():
    """A blob that deliberately carries no transform must not have one put
    back from an older copy."""
    merged = ts.carry_forward({"model_type": "logistic"}, {"model_type": "logistic"})
    assert ts.SOURCE not in merged


def test_carry_forward_does_not_overwrite_an_explicit_new_transform():
    new = ts.encode("def transform(df):\n    return df.assign(y=2.0)\n")
    old = ts.encode(SRC)

    merged = ts.carry_forward(dict(new), old)
    assert ts.decode(merged)["source"] != SRC
    assert ts.decode(merged)["sha256"] == new[ts.SHA]


def test_every_transform_key_is_carried():
    """A key added later and not carried would leave the stored record
    half-updated - a source with someone else's checksum beside it."""
    existing = ts.encode(SRC, author="alice")
    merged = ts.carry_forward({}, existing)

    assert set(ts.KEYS) <= set(merged)
