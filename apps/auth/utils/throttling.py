"""Rate limit del login de admin (`POST /api/admin/login/`).

Un login de staff sin tope es fuerza bruta gratis contra el hash.
"""
from rest_framework.throttling import SimpleRateThrottle


class _IpRateThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        # Se agrupa por IP: el identificador lo elige quien ataca.
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class AdminLoginRateThrottle(_IpRateThrottle):
    scope = "admin_login"


class RegisterRateThrottle(_IpRateThrottle):
    scope = "register"
