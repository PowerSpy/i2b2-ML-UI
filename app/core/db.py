import csv, io, re, shlex, sys

from app.core.config import settings
from app.core.docker_exec import exec

# csv caps a single field at 128 KB by default, and a built model's blob blows
# straight past that: the serialized model plus five base64 plot PNGs runs to
# several hundred KB in one concept_blob cell. Without this, reading one fails
# with "field larger than field limit". sys.maxsize overflows the C long this
# takes on Windows, so step down until one is accepted.
_limit = sys.maxsize
while True:
    try:
        csv.field_size_limit(_limit)
        break
    except OverflowError:
        _limit //= 2

SAFE_CODE = re.compile(r"^[A-Za-z0-9_:-]{1,50}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
SAFE_PATH = re.compile(r"^/?([A-Za-z0-9_ .-]+/)*[A-Za-z0-9_ .-]+/?$")

# Todo: Remove throwing logic and replace with normalization when given an unsafe input

def check_code(code: str) -> str:
    if not SAFE_CODE.match(code or ""):
        raise ValueError(f"unsafe concept code: {code!r}")
    return code


def check_name(name: str) -> str:
    if not SAFE_NAME.match(name or ""):
        raise ValueError(f"unsafe cohort name: {name!r}")
    return name


def check_path(path: str) -> str:
    if not SAFE_PATH.match(path or ""):
        raise ValueError(f"unsafe concept path: {path!r}")
    return path


def query(sql: str, timeout: float = 60.0) -> list[dict]:
    out = exec(settings.db_container,
               f"{settings.psql} --csv -c {shlex.quote(sql)}",
               timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "psql failed")
    return list(csv.DictReader(io.StringIO(out.stdout)))


def scalar(sql: str) -> str | None:
    rows = query(sql)
    return next(iter(rows[0].values())) if rows else None