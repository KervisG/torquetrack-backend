"""Rate limit de los endpoints públicos de cuenta: login, registro y
activación del portal.

Un login sin tope es fuerza bruta gratis contra el hash, y un registro o
una activación sin tope sirven para crear cuentas en masa o adivinar tokens.
"""
import hashlib

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


def get_client_ip(request):
    """IP del cliente para agrupar intentos.

    Nunca se lee `X-Forwarded-For`: sin un proxy de confianza lo escribe el
    propio cliente, y rotarlo abriría una cuota nueva en cada request. Solo se
    acepta el header que `CLIENT_IP_HEADER` declara como confiable (en
    producción, el que inyecta Cloudflare); si no está, manda `REMOTE_ADDR`.
    """
    header = settings.CLIENT_IP_HEADER
    if header:
        value = request.META.get(header, "").strip()
        if value:
            return value
    return request.META.get("REMOTE_ADDR")


class _IpRateThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        # Se agrupa por IP: el identificador lo elige quien ataca.
        return self.cache_format % {
            "scope": self.scope,
            "ident": get_client_ip(request),
        }


class LoginRateThrottle(_IpRateThrottle):
    scope = "login"


class RegisterRateThrottle(_IpRateThrottle):
    scope = "register"


class ActivateRateThrottle(_IpRateThrottle):
    scope = "activate"


class LoginAccountRateThrottle(SimpleRateThrottle):
    """Tope por cuenta atacada, para que repartir el ataque entre muchas IPs
    no esquive el límite por IP."""

    scope = "login_account"

    def get_cache_key(self, request, view):
        body = request.data if isinstance(request.data, dict) else {}
        identifier = body.get("email")
        if not isinstance(identifier, str) or not identifier.strip():
            return None
        # Se hashea para que los emails no queden en claro en las keys del cache.
        digest = hashlib.sha256(identifier.strip().lower().encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}
