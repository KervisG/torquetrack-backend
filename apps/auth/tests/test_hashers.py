"""RED/GREEN evidence for `ScryptLegacyHasher` (design decision #5, task 3.1).

The frozen Next.js app (`lib/auth.ts`) hashes passwords as
``scrypt$<16-byte-hex-salt>$<64-byte-scrypt-digest-hex>`` using Node's
``crypto.scryptSync(password, salt, 64)``. Node's documented scrypt
defaults are N=16384, r=8, p=1 — verified in this session to produce a
byte-for-byte identical digest to Python's
``hashlib.scrypt(password, salt=salt, n=16384, r=8, p=1, dklen=64)`` for
the same password/salt pair, so this test uses a REAL reproduction of the
current algorithm, not an invented format.
"""
import hashlib

import pytest
from django.contrib.auth.hashers import check_password, make_password

from apps.auth.hashers import ScryptLegacyHasher

_REAL_SALT = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"


def _legacy_hash(password: str, salt: str = _REAL_SALT) -> str:
    """Reproduce `lib/auth.ts`'s `hashPassword()` exactly."""
    digest = hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64
    )
    return f"scrypt${salt}${digest.hex()}"


def test_verify_accepts_the_correct_password_against_a_real_legacy_hash():
    stored = _legacy_hash("correct-horse-battery-staple")

    assert ScryptLegacyHasher().verify("correct-horse-battery-staple", stored) is True


def test_verify_rejects_an_incorrect_password_against_a_real_legacy_hash():
    stored = _legacy_hash("correct-horse-battery-staple")

    assert ScryptLegacyHasher().verify("wrong-password", stored) is False


def test_must_update_is_always_true_so_legacy_hashes_rehash_on_login():
    stored = _legacy_hash("correct-horse-battery-staple")

    assert ScryptLegacyHasher().must_update(stored) is True


def test_check_password_rehashes_to_the_preferred_hasher_via_setter():
    """Exercises the exact `django.contrib.auth.hashers.check_password`
    entry point a login view will call — proves the full "verify legacy,
    then rehash to Django's standard hasher" path from design decision #5,
    not just the isolated hasher class.
    """
    stored = _legacy_hash("correct-horse-battery-staple")
    captured = {}

    def setter(raw_password):
        captured["new_hash"] = make_password(raw_password)

    is_correct = check_password(
        "correct-horse-battery-staple", stored, setter=setter
    )

    assert is_correct is True
    assert "new_hash" in captured
    assert not captured["new_hash"].startswith("scrypt$")


def test_check_password_does_not_call_setter_on_wrong_password():
    stored = _legacy_hash("correct-horse-battery-staple")
    captured = {}

    def setter(raw_password):
        captured["called"] = True

    is_correct = check_password("wrong-password", stored, setter=setter)

    assert is_correct is False
    assert "called" not in captured


@pytest.mark.parametrize("garbage", ["not-scrypt-at-all", "scrypt$onlyonepart", ""])
def test_verify_rejects_malformed_encoded_values_instead_of_raising(garbage):
    assert ScryptLegacyHasher().verify("any-password", garbage) is False
