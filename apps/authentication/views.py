"""Una sola cuenta para clientes y staff: entrar no da acceso al panel, eso lo
decide el Role."""
from django.contrib.auth import login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import User
from apps.authentication.services import (
    authenticate_user,
    confirm_password_reset,
    csrf_token_payload,
    request_password_reset,
    resend_verification_email,
    serialize_session_user,
)
from apps.authentication.utils.throttling import (
    LoginAccountRateThrottle,
    LoginRateThrottle,
    PasswordResetAccountRateThrottle,
    PasswordResetConfirmRateThrottle,
    PasswordResetRateThrottle,
    VerifyEmailResendRateThrottle,
)


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _session_payload(request, user: User) -> dict:
    return {
        "authenticated": True,
        "user": serialize_session_user(user),
        **csrf_token_payload(request),
    }


class LoginView(APIView):
    # Solo JSON: un formulario de otro sitio no puede mandar `application/json`
    # sin preflight de CORS, así que no llega a esta ruta sin CSRF (415).
    parser_classes = [JSONParser]
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle, LoginAccountRateThrottle]

    def post(self, request):
        body = _body(request)
        user = authenticate_user(request, body.get("email"), body.get("password"))
        if user is None:
            return Response({"error": "Incorrect email or password"}, status=401)
        # `login()` rota la session key (anti fijación) y el token CSRF, y
        # conserva los datos de la sesión anónima, como el carrito.
        login(request, user)
        return Response(_session_payload(request, user))


class LogoutView(APIView):
    """Autentica con la sesión para que un logout cross-site sin token CSRF
    no pueda cerrar la sesión de otra persona."""

    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response({"ok": True})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SessionView(APIView):
    """Entrega el token CSRF (cookie y body) al SPA aunque todavía no haya sesión."""

    permission_classes = [AllowAny]

    def get(self, request):
        if not request.user.is_authenticated:
            return Response(
                {"error": "Unauthorized", **csrf_token_payload(request)}, status=401
            )
        return Response(_session_payload(request, request.user))


def _result(result: dict) -> Response:
    if "error" in result:
        return Response({"error": result["error"]}, status=result["status"])
    return Response(result)


class PasswordResetView(APIView):
    parser_classes = [JSONParser]
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetRateThrottle, PasswordResetAccountRateThrottle]

    def post(self, request):
        return Response(request_password_reset(_body(request)))


class PasswordResetConfirmView(APIView):
    parser_classes = [JSONParser]
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetConfirmRateThrottle]

    def post(self, request):
        return _result(confirm_password_reset(_body(request)))


class VerifyEmailResendView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [VerifyEmailResendRateThrottle]

    def post(self, request):
        if not request.user.is_authenticated:
            return Response({"error": "Unauthorized"}, status=401)
        return Response(resend_verification_email(request.user))
