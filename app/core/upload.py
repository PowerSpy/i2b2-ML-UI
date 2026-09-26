"""Turning an uploaded filename into something safe to put in a shell command.

The loader stages an upload on the host, `docker cp`s the directory into the
ETL container, and runs `python -m i2b2_cdi <kind> load -i <dir>` there through
`bash -lc`. Every one of those steps takes a string that originally came from a
multipart header.

Two things matter and only one of them is obvious:

1. The **filename** is attacker-controlled.
2. The **directory** was too. The old code derived it from
   `Path(file.filename).stem`, and that is the value that actually reached the
   shell — validating the filename alone would have closed the reported hole
   and left an identical one beside it. The staging directory is now generated
   by `tempfile.mkdtemp`, so nothing caller-derived appears in the command.

The regexes follow the same allowlist idiom as `app/core/db.py`: reject, do not
normalise. A normalising cleaner has to be right about every input; an
allowlist only has to be right about the ones it accepts.
"""

from pathlib import PurePosixPath, PureWindowsPath

import re

# Deliberately narrow. Anything outside this is rejected rather than stripped,
# so a name that "almost" works fails loudly at upload instead of quietly
# loading nothing.
SAFE_UPLOAD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")

# The suffix the i2b2 loader globs for. It takes a *directory* and matches on
# the name, so a file that does not end this way is skipped silently and the
# CLI still exits 0 - see the note in app/api/loader.py.
SUFFIX = {"concept": "concepts.csv", "fact": "facts.csv"}

# Uploads are staged on the host and copied into the container, so an
# unbounded one costs disk twice before anything validates it.
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


def safe_upload_name(raw: str | None, *, kind: str) -> str:
    """The basename of `raw`, or ValueError explaining why not.

    `kind` is "concept" or "fact" and decides the required suffix.
    """
    if kind not in SUFFIX:
        raise ValueError(f"unknown upload kind {kind!r}")

    if raw is None or not raw.strip():
        raise ValueError("the upload has no filename")

    if "\x00" in raw:
        raise ValueError("filename contains a null byte")

    # Both separators, deliberately. On a POSIX host `PurePosixPath` leaves
    # "a\\b.csv" whole; on Windows `PureWindowsPath` leaves "a/b.csv" whole.
    # Neither alone strips a path on both, and this backend runs on both.
    name = PureWindowsPath(PurePosixPath(raw).name).name

    if name in (".", "..", ""):
        raise ValueError(f"{raw!r} is not a filename")

    if not SAFE_UPLOAD.fullmatch(name):
        raise ValueError(
            f"{name!r} is not an acceptable filename. Use letters, digits, "
            "dot, underscore and hyphen only, starting with a letter or "
            "digit, up to 120 characters."
        )

    expected = SUFFIX[kind]
    if not name.lower().endswith(expected):
        # Checked here rather than after the load. The loader globs a
        # directory by suffix, so a name that does not match ingests nothing
        # and still exits 0 - which used to surface as a puzzled note attached
        # to a successful-looking response.
        raise ValueError(
            f"{name!r} does not end {expected!r}. The i2b2 loader globs its "
            "input directory by suffix and silently ignores anything else, so "
            "this would have loaded nothing and reported success."
        )

    return name


def write_capped(src, dest, limit: int = MAX_UPLOAD_BYTES) -> int:
    """Stream `src` to `dest`, refusing to exceed `limit`.

    Counted while copying rather than read from Content-Length, which the
    client sets and can lie about. Returns the byte count.
    """
    total = 0
    with open(dest, "wb") as fh:
        while chunk := src.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError(
                    f"upload exceeds the {limit // (1024 * 1024)} MB limit"
                )
            fh.write(chunk)
    return total
