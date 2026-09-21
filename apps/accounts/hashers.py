"""Password hasher compatible with the frozen Next.js app's scrypt format
(`lib/auth.ts`: `hashPassword` / `verifyPassword`), per design decision #5.

On-disk format: ``scrypt$<16-byte-hex-salt>$<64-byte-scrypt-digest-hex>``,
produced by Node's ``crypto.scryptSync(password, salt, 64)``. Node's
documented scrypt defaults are N=16384 (cost), r=8 (block size), p=1
(parallelism) — verified in this session to produce a byte-for-byte
identical digest to Python's ``hashlib.scrypt`` with the same parameters
for the same password/salt pair.

``algorithm = "scrypt"`` intentionally reuses the exact literal prefix the
existing rows already use, so ``django.contrib.auth.hashers.identify_hasher``
(which reads the text before the first ``$``) resolves to THIS hasher for
those rows. Django ships its own ``ScryptPasswordHasher`` with the SAME
``algorithm = "scrypt"`` but a different 6-part encoding
(``scrypt$n$salt$r$p$hash``) — it is intentionally NOT listed in
``PASSWORD_HASHERS`` (see `config/settings/base.py`) so there is no
collision at runtime; `get_hashers_by_algorithm()` would otherwise let the
last-listed "scrypt" hasher win.

``must_update`` always returns ``True`` so
``django.contrib.auth.hashers.check_password(..., setter=...)`` rehashes to
the preferred (first-listed) hasher on the next successful login.
"""

import hashlib

from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from django.utils.crypto import constant_time_compare
from django.utils.translation import gettext_noop as _

LEGACY_SCRYPT_N = 16384
LEGACY_SCRYPT_R = 8
LEGACY_SCRYPT_P = 1
LEGACY_SCRYPT_DKLEN = 64


class ScryptLegacyHasher(BasePasswordHasher):
    """Verifies legacy `scrypt$salt$hash` rows; never used to encode new
    passwords going forward (see module docstring)."""

    algorithm = "scrypt"

    def encode(self, password, salt):
        self._check_encode_args(password, salt)
        digest = hashlib.scrypt(
            password.encode(),
            salt=salt.encode(),
            n=LEGACY_SCRYPT_N,
            r=LEGACY_SCRYPT_R,
            p=LEGACY_SCRYPT_P,
            dklen=LEGACY_SCRYPT_DKLEN,
        )
        return f"{self.algorithm}${salt}${digest.hex()}"

    def decode(self, encoded):
        algorithm, salt, hash_hex = encoded.split("$", 2)
        assert algorithm == self.algorithm
        return {"algorithm": algorithm, "salt": salt, "hash": hash_hex}

    def verify(self, password, encoded):
        try:
            decoded = self.decode(encoded)
        except (ValueError, AssertionError):
            return False
        expected = self.encode(password, decoded["salt"])
        return constant_time_compare(encoded, expected)

    def safe_summary(self, encoded):
        decoded = self.decode(encoded)
        return {
            _("algorithm"): decoded["algorithm"],
            _("salt"): mask_hash(decoded["salt"]),
            _("hash"): mask_hash(decoded["hash"]),
        }

    def must_update(self, encoded):
        return True

    def harden_runtime(self, password, encoded):
        # Legacy verification always triggers a rehash to the preferred
        # hasher via `must_update`; there is no separate work-factor
        # migration path within the legacy scheme itself.
        pass
