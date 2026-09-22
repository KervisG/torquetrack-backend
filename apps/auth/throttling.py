"""Rate limit del login de admin (`POST /api/admin/login`).

El Next.js congelado no limita ningún endpoint, así que esto es una mejora
deliberada sobre el contrato legado y no un port: un login de staff sin tope
es fuerza bruta gratis contra `users.password_hash`.
"""
from rest_framework.throttling import SimpleRateThrottle


class AdminLoginRateThrottle(SimpleRateThrottle):
    scope = "admin_login"

    def get_cache_key(self, request, view):
        # Se agrupa por IP y no por username: el username lo elige quien
        # ataca, así que un tope por username se evade rotándolo.
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
