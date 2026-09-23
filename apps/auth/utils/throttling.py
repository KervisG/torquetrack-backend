"""Rate limit de los endpoints públicos de cuenta: login, registro,
activación del portal, restablecer contraseña y verificar el email.

Un login sin tope es fuerza bruta gratis contra el hash, y un registro o
una activación sin tope sirven para crear cuentas en masa o adivinar tokens.
Un pedido de reset sin tope convierte el formulario en un cañón de correos
contra la casilla de un tercero.
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


class PasswordResetRateThrottle(_IpRateThrottle):
    scope = "password_reset"


class PasswordResetConfirmRateThrottle(_IpRateThrottle):
    scope = "password_reset_confirm"


class VerifyEmailRateThrottle(_IpRateThrottle):
    scope = "verify_email"


class VerifyEmailResendRateThrottle(SimpleRateThrottle):
    """Tope por cuenta: el reenvío exige sesión, así que se agrupa por el
    usuario y no por la IP."""

    scope = "verify_email_resend"

    def get_cache_key(self, request, view):
        user_id = getattr(request.user, "pk", None)
        if not user_id:
            return self.cache_format % {"scope": self.scope, "ident": get_client_ip(request)}
        return self.cache_format % {"scope": self.scope, "ident": user_id}


class _EmailRateThrottle(SimpleRateThrottle):
    """Tope por correo del body, para que repartir el ataque entre muchas IPs
    no esquive el límite por IP."""

    def get_cache_key(self, request, view):
        body = request.data if isinstance(request.data, dict) else {}
        identifier = body.get("email")
        if not isinstance(identifier, str) or not identifier.strip():
            return None
        # Se hashea para que los emails no queden en claro en las keys del cache.
        digest = hashlib.sha256(identifier.strip().lower().encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}


class LoginAccountRateThrottle(_EmailRateThrottle):
    scope = "login_account"


class PasswordResetAccountRateThrottle(_EmailRateThrottle):
    # Cuenta igual exista o no el correo, así el 429 no revela si hay cuenta.
    scope = "password_reset_account"
