"""Password hashing, on the standard library.

No new dependency. `requirements.txt` is seven lines and this codebase runs on
Python 3.14, where bcrypt/argon2-cffi want compiled wheels and passlib is
unmaintained. `hashlib.scrypt` is memory-hard, ships with CPython, and is the
right answer for a handful of accounts on an internal server.

The stored string is self-describing:

    scrypt$32768$8$1$<b64 salt>$<b64 derived key>

so the cost parameters can be raised later without a migration - `needs_rehash`
tells you which stored hashes predate the change, and they are upgraded the
next time that user logs in and the plaintext is briefly available.
"""

import hashlib
import hmac
import secrets
from base64 import b64decode, b64encode

# ~32 MB per hash at these settings. Deliberate: it is what makes an offline
# attack on a leaked database expensive, and this app authenticates a few
# people a day, not thousands a second.
N = 2 ** 15
R = 8
P = 1
DKLEN = 32
SALT_BYTES = 16

# OpenSSL's default cap is around 32 MB, which N=32768/r=8 sits exactly on.
# Without this, hashing raises rather than being slow.
MAXMEM = 128 * 1024 * 1024

SCHEME = "scrypt"

# Short passwords are the only rule worth enforcing. Composition rules
# (a digit, a symbol, a capital) measurably produce worse passwords - people
# satisfy them with predictable substitutions - so length is all this checks.
MIN_LENGTH = 12


class PasswordError(ValueError):
    """A password that cannot be accepted, with a reason fit to show a user."""


def validate(plain: str) -> str:
    if not plain or len(plain) < MIN_LENGTH:
        raise PasswordError(
            f"password must be at least {MIN_LENGTH} characters"
        )
    return plain


def _derive(plain: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        plain.encode("utf8"), salt=salt, n=n, r=r, p=p,
        dklen=dklen, maxmem=MAXMEM,
    )


def hash_password(plain: str) -> str:
    validate(plain)
    salt = secrets.token_bytes(SALT_BYTES)
    dk = _derive(plain, salt, N, R, P, DKLEN)
    return "$".join([
        SCHEME, str(N), str(R), str(P),
        b64encode(salt).decode(), b64encode(dk).decode(),
    ])


def verify_password(plain: str, stored: str) -> bool:
    """True if `plain` matches `stored`.

    Returns False for a malformed or unknown-scheme hash rather than raising:
    a corrupt row in the user table must fail the login, not 500 the endpoint
    and tell the caller the row is corrupt.
    """
    try:
        scheme, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if scheme != SCHEME:
            return False
        salt = b64decode(salt_b64)
        expected = b64decode(dk_b64)
        actual = _derive(plain, salt, int(n), int(r), int(p), len(expected))
    except Exception:  # noqa: BLE001 - any parse failure is a failed login
        return False

    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    """True if `stored` was made with weaker parameters than current."""
    try:
        scheme, n, r, p, _salt, _dk = stored.split("$")
    except ValueError:
        return True
    return scheme != SCHEME or (int(n), int(r), int(p)) != (N, R, P)
