"""Storing a researcher's Python in the concept blob, intact.

## Why base64 and not the source

The blob has **two encodings depending on how it was written**, and the reader
cannot tell them apart:

- **Create** (`POST /etl/concepts`) goes through `csv.writer`, so the blob
  lands as a Python **repr** - single quotes.
- **Update** (`PUT /etl/concepts`) passes the blob as a query parameter,
  written verbatim by a parameterised UPDATE, so it lands as real **JSON** -
  double quotes.

The container's reader is unconditional (`BaseEngine.py:53`,
`build_model_ML_helper.py:424`):

```python
json.loads(blob.replace("'", '"'))
```

On the repr that swap is a *repair*. On the JSON it is *damage* - it rewrites
every apostrophe inside every string value into a `"` and breaks the parse.

The PUT path is the one every **edited** model takes, which is exactly the
iterate-on-your-code workflow this feature invites. Save fine on first create,
add a comment with an apostrophe on the second save, and the build dies with
`Expecting value: line 1 column N` naming nothing.

Base64's alphabet is `A-Za-z0-9+/=`. No quote, no backslash, no newline, so it
is byte-identical through both paths. That is not belt-and-braces; it is the
only encoding that survives.

## Why the write is read back

`workspace.jsx` states the doctrine - nothing reports success off a write's own
response - and this is the payload most likely to be silently mangled. Every
save re-reads the blob and checks the stored source still hashes to what was
sent. A transform that was accepted and corrupted is worse than one rejected,
because the corruption surfaces later, inside a build, as somebody else's
error.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime, timezone

from app.core import audit, etl_api, ml_blob

# Blob keys. Prefixed so `strip_heavy` and the plot-key sweep never collide
# with them, and so they are obvious in a raw blob dump.
SOURCE = "transform_b64"
SHA = "transform_sha256"
SAVED_AT = "transform_saved_at"
AUTHOR = "transform_author"

KEYS = (SOURCE, SHA, SAVED_AT, AUTHOR)

# Measured against this ETL rather than guessed, because the update path
# carries the **whole blob as a query parameter**:
#
#     32 KB source  -> ~44 KB URL -> accepted
#     64 KB source  -> ~89 KB URL -> HTTP 414 URI Too Long
#
# 24 KB of source is ~32 KB of base64, leaving room for the model config
# alongside it. A transform is a function, not a library; anything approaching
# this is the wrong shape for the blob and should become a file.
#
# Re-measure with `probe_url_limit` if the ETL's server changes - gunicorn's
# `limit_request_line` defaults to 4094 bytes, so a deployment change could
# make this an order of magnitude smaller without warning.
MAX_SOURCE_BYTES = 24 * 1024

# Above this, a dropped connection is read as "the request line was too long"
# rather than as a network problem. Comfortably above a normal blob and well
# below the ~89 KB where this ETL starts refusing, so a genuine network blip on
# a small payload still surfaces as itself.
TOO_LONG_HINT_BYTES = 48 * 1024


class TransformError(Exception):
    """A refusal with a sentence a researcher can act on."""


# --------------------------------------------------------------------------
# encoding


def validate(source: str) -> str:
    """Check what the editor accepted before anything is written."""
    if not isinstance(source, str):
        raise TransformError("the transform must be text")

    stripped = source.strip()
    if not stripped:
        raise TransformError("the transform is empty")

    encoded = source.encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise TransformError(
            f"the transform is {len(encoded)} bytes; the limit is "
            f"{MAX_SOURCE_BYTES}. It is stored inside the model's concept blob, "
            "which travels in a URL when the model is updated."
        )

    if "\x00" in source:
        raise TransformError("the transform contains a null byte")

    return source


def encode(source: str, *, author: str | None = None) -> dict:
    """The blob fields for `source`.

    The digest is over the **raw bytes**, not the base64, so it verifies the
    thing that matters rather than the envelope it travelled in.
    """
    raw = validate(source).encode("utf-8")
    return {
        SOURCE: base64.b64encode(raw).decode("ascii"),
        SHA: hashlib.sha256(raw).hexdigest(),
        SAVED_AT: datetime.now(timezone.utc).isoformat(timespec="seconds"),
        AUTHOR: author,
    }


def decode(blob: dict) -> dict | None:
    """The transform in `blob`, or None. Never raises on a damaged one.

    A corrupt payload is reported as corrupt rather than crashing the model
    page - the researcher needs to see the model to fix or clear it.
    """
    packed = (blob or {}).get(SOURCE)
    if not packed:
        return None

    stored_sha = blob.get(SHA)
    try:
        raw = base64.b64decode(packed, validate=True)
        source = raw.decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError) as e:
        return {
            "source": None, "sha256": stored_sha, "saved_at": blob.get(SAVED_AT),
            "author": blob.get(AUTHOR), "intact": False,
            "problem": (
                f"the stored transform could not be decoded ({e}). The blob has "
                "been damaged since it was written; the source is not "
                "recoverable from here."
            ),
        }

    actual = hashlib.sha256(raw).hexdigest()
    intact = stored_sha is None or actual == stored_sha
    return {
        "source": source,
        "sha256": actual,
        "saved_at": blob.get(SAVED_AT),
        "author": blob.get(AUTHOR),
        "intact": intact,
        "problem": None if intact else (
            "the stored transform does not match its recorded checksum. It "
            "decoded, but it is not the text that was saved - do not build "
            "from it without reviewing it."
        ),
    }


def carry_forward(new_blob: dict, existing: dict) -> dict:
    """Preserve the transform across a model-config save.

    `ModelForm` builds its blob from scratch and the backend writes it whole,
    so without this, saving the algorithm or a cohort **silently deletes the
    transform** - and the next build trains a different model and reports
    success.

    Doing it here rather than asking every form to remember is the safer half:
    a future form that knows nothing about transforms still cannot destroy one.
    """
    for key in KEYS:
        if key in existing and key not in new_blob:
            new_blob[key] = existing[key]
    return new_blob


# --------------------------------------------------------------------------
# reading and writing


def load(code: str) -> dict | None:
    """The transform stored against `code`, or None."""
    return decode(ml_blob.load_blob_light(code))


def sha_of(code: str) -> str | None:
    """The recorded digest, without decoding anything.

    Used to tie a build or an apply to the exact code that produced it.
    """
    try:
        return ml_blob.load_blob_light(code).get(SHA)
    except KeyError:
        return None


def save(code: str, path: str, source: str, *, author: str | None = None) -> dict:
    """Write `source` into the model's blob and confirm it survived.

    Returns the verified record, carrying `discarded_build` when a trained
    model was dropped to make the write possible - see `_write`. Raises
    `TransformError` if the round trip does not match, because a transform
    that was accepted and corrupted is worse than one that was refused.
    """
    was_built = ml_blob.is_built(code)
    fields = encode(source, author=author)
    _write(code, path, fields)
    record = _verify(code, fields[SHA], "saved")
    record["discarded_build"] = was_built
    return record


def clear(code: str, path: str) -> None:
    """Remove the transform, and confirm it is gone."""
    _write(code, path, {k: None for k in KEYS}, dropping=True)

    after = load(code)
    if after is not None:
        raise TransformError(
            "the transform was deleted but is still present when read back."
        )
    audit.event("transform_cleared", subject=code, path=path)


def _write(code: str, path: str, fields: dict, *, dropping: bool = False) -> None:
    """Merge `fields` into the stored blob via the ETL's update path.

    Read-modify-write, because the endpoint replaces the whole blob. The race
    that implies is real but narrow - two people editing one model at once -
    and the alternative is an endpoint the platform does not offer.

    **The light blob, not the full one**, and that has a consequence worth
    stating: `load_blob_light` drops `serialized_model` and the plot PNGs, so
    writing it back **discards the trained model**. Two reasons that is the
    right call rather than a compromise:

    1. The update path carries the blob as a *query parameter*. A built blob
       is 611 KB on this instance, and that is not a URL.
    2. A model trained under one transform must not be applied under another -
       the apply path is required to refuse on a `transform_sha256` mismatch.
       Keeping the old estimator would preserve something already invalid.

    `is_built` keys off `serialized_model`, so the model correctly reports
    unbuilt afterwards rather than looking trained. Callers surface it as a
    warning; it is never silent.
    """
    try:
        blob = ml_blob.load_blob_light(code)
    except KeyError:
        raise TransformError(
            f"no model {code!r} to attach a transform to. Save the model "
            "configuration first."
        )

    for key, value in fields.items():
        if value is None and dropping:
            blob.pop(key, None)
        else:
            blob[key] = value

    # A null anywhere in the blob corrupts it: the container's repair swaps
    # quotes and then parses, and `None` is not JSON. The dict is rebuilt
    # without them rather than trusting every caller.
    blob = {k: v for k, v in blob.items() if v is not None}

    payload = json.dumps(blob)
    try:
        etl_api.put("/etl/concepts", params={
            "cpath": "\\" + path.strip("/").replace("/", "\\") + "\\",
            "blob": payload,
        })
    except Exception as e:
        # An over-long request line has two observed endings, and only one of
        # them is an HTTP status: at ~89 KB this ETL answers 414, and at a few
        # hundred KB it closes the connection without replying at all. Both
        # mean the same thing and both arrive as something unreadable - an
        # HTML error page or a RemoteDisconnected - so both get the sentence.
        #
        # `validate` bounds the transform itself, but the rest of the blob
        # shares that URL, so a model with many data paths or a large
        # hyperparameter grid can cross the line on its own.
        dropped = any(
            marker in type(e).__name__ or marker in str(e)
            for marker in ("ConnectionError", "RemoteDisconnected",
                           "Connection aborted")
        )
        if "414" in str(e) or (dropped and len(payload) > TOO_LONG_HINT_BYTES):
            raise TransformError(
                f"the model's blob is too large to update ({len(payload)} "
                "bytes). It travels in a URL, and this server will not accept "
                "one that long. Shorten the transform, or reduce the model's "
                "data paths and hyperparameter grid."
            ) from None
        raise


def _verify(code: str, expected_sha: str, action: str) -> dict:
    record = load(code)

    if record is None:
        raise TransformError(
            f"the transform was {action} but is not there when read back. "
            "Nothing was stored."
        )
    if not record["intact"]:
        raise TransformError(f"the transform was {action} but {record['problem']}")
    if record["sha256"] != expected_sha:
        raise TransformError(
            f"the transform was {action} but came back different "
            f"({record['sha256'][:12]} rather than {expected_sha[:12]}). "
            "The stored blob has been mangled in transit; do not build from it."
        )

    audit.event("transform_saved", subject=code, sha256=expected_sha,
                source_bytes=len(record["source"].encode("utf-8")))
    return record


# --------------------------------------------------------------------------


def probe_url_limit(code: str, path: str, *, start: int = 4096,
                    ceiling: int = 512 * 1024) -> int:
    """The largest blob this ETL will actually accept on the update path.

    Not used at runtime. It is here because `MAX_SOURCE_BYTES` is otherwise a
    guess: the blob travels as a **query parameter**, and the practical limit
    is whatever the ETL's WSGI server allows on a request line - gunicorn
    defaults to 4094 bytes, which would reject almost anything.

    Doubles a payload until a write stops coming back intact. Writes to a real
    concept, so call it against one you are willing to modify.
    """
    size, last_ok = start, 0
    while size <= ceiling:
        filler = "# " + ("x" * (size - 2))
        try:
            save(code, path, f"def transform(df):\n    return df\n{filler}\n")
            last_ok = size
        except Exception:
            break
        size *= 2
    return last_ok
