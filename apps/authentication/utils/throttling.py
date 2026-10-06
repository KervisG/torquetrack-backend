"""Un login sin tope es fuerza bruta gratis contra el hash, y un registro o
una activación sin tope sirven para crear cuentas en masa o adivinar tokens.
Un pedido de reset sin tope convierte el formulario en un cañón de correos
contra la casilla de un tercero.

Las rutas públicas del storefront que cuestan (sesión de Stripe, correos,
WeasyPrint, EasyPost, TaxJar, NHTSA) también tienen tope por IP: sin él,
cualquiera las usa para gastar la cuota paga de un proveedor o saturar los
workers. Viven acá y no en cada app porque este módulo es la infraestructura
de request que todas las views ya importan sin crear una dependencia de
dominio (`tests/test_app_boundaries.py`), y `apps/common/` no importa DRF.
"""
import hashlib

from django.conf import settings
from rest_framework.throttling import BaseThrottle, SimpleRateThrottle


def get_client_ip(request):
    """Sin un proxy de confianza `X-Forwarded-For` lo escribe el propio
    cliente, y rotarlo abriría una cuota nueva en cada request. Primero manda
    el header que `CLIENT_IP_HEADER` declara como confiable (el que inyecta
    un proxy de confianza). Si no, `get_ident` de DRF con `NUM_PROXIES`: en 0 (el default)
    es `REMOTE_ADDR`; en N toma la entrada que agregó el proxy más externo de
    los N, así lo que el cliente haya puesto antes no cuenta.
    """
    header = settings.CLIENT_IP_HEADER
    if header:
        value = request.META.get(header, "").strip()
        if value:
            return value
    return BaseThrottle().get_ident(request)


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
    """Cuenta solo los intentos FALLIDOS por email: si contara todos, cualquiera
    podría bloquear una cuenta ajena tipeando su email, y el dueño no podría
    entrar ni con la contraseña correcta. `allow_request` solo mira el
    historial; la view suma un fallo con `record_failure` tras credenciales
    inválidas y lo reinicia con `reset` al entrar. El tope por IP
    (`LoginRateThrottle`) sigue contando todos los intentos."""

    scope = "login_account"

    def throttle_success(self):
        return True

    def _history_key(self, request):
        if self.rate is None:
            return None
        return self.get_cache_key(request, None)

    def record_failure(self, request):
        key = self._history_key(request)
        if key is None:
            return
        now = self.timer()
        history = [moment for moment in self.cache.get(key, []) if moment > now - self.duration]
        history.insert(0, now)
        self.cache.set(key, history, self.duration)

    def reset(self, request):
        key = self._history_key(request)
        if key is not None:
            self.cache.delete(key)


class PasswordResetAccountRateThrottle(_EmailRateThrottle):
    # Cuenta igual exista o no el correo, así el 429 no revela si hay cuenta.
    scope = "password_reset_account"


class CheckoutRateThrottle(_IpRateThrottle):
    # Cada intento crea un pedido `PENDING_PAYMENT` y una sesión de Stripe.
    scope = "checkout"


class QuoteCheckoutRateThrottle(_IpRateThrottle):
    # Pagar una cotización también abre una sesión de Stripe.
    scope = "quote_checkout"


class QuoteRequestRateThrottle(_IpRateThrottle):
    # Cada solicitud guarda una cotización y manda dos correos.
    scope = "quote_request"


class QuotePdfRateThrottle(_IpRateThrottle):
    # WeasyPrint ocupa un worker varios segundos por PDF.
    scope = "quote_pdf"


class ShippingRatesRateThrottle(_IpRateThrottle):
    scope = "shipping_rates"


class TaxEstimateRateThrottle(_IpRateThrottle):
    scope = "tax_estimate"


class VinDecodeRateThrottle(_IpRateThrottle):
    scope = "vin_decode"


class FitmentCheckRateThrottle(_IpRateThrottle):
    scope = "fitment_check"
