"""Hasher `scrypt$salt$hash` para filas que todavía usan ese formato.

`algorithm = "scrypt"` reutiliza el prefijo de esas filas para que
`identify_hasher` resuelva a esta clase. Django trae otro
`ScryptPasswordHasher` con el mismo algoritmo y otro encoding: no está
en `PASSWORD_HASHERS` para que no gane el último listado.

`must_update` siempre es True, pero el login no pasa `setter=`:
rehashear a PBKDF2 dejaría esas filas ilegibles para quien aún verifica scrypt.
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
    """Solo verifica filas scrypt; no se usa para hashear passwords nuevos."""

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
        pass
