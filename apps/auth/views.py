"""`register`, `login`, `logout` y `session`: una sola cuenta para clientes
y staff. Entrar no da acceso al panel; eso lo decide el Role.
"""
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.authentication import SessionUserAuthentication
from apps.auth.models import User
from apps.auth.services import (
    authenticate_user,
    register_customer,
    serialize_session_user,
)
from apps.auth.sessions import (
    csrf_token_payload,
    end_user_session,
    start_user_session,
)
from apps.auth.utils.throttling import (
    LoginAccountRateThrottle,
    LoginRateThrottle,
    RegisterRateThrottle,
)


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _session_payload(request, user: User) -> dict:
    return {
        "authenticated": True,
        "user": serialize_session_user(user),
        **csrf_token_payload(request),
    }


class RegisterView(APIView):
    """`POST /api/register/`."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [RegisterRateThrottle]

    def post(self, request):
        result = register_customer(_body(request))
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        start_user_session(request, result["user"])
        return Response(_session_payload(request, result["user"]), status=201)


class LoginView(APIView):
    """`POST /api/login/`."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle, LoginAccountRateThrottle]

    def post(self, request):
        body = _body(request)
        user = authenticate_user(body.get("email"), body.get("password"))
        if user is None:
            return Response({"error": "Incorrect email or password"}, status=401)
        start_user_session(request, user)
        return Response(_session_payload(request, user))


class LogoutView(APIView):
    """`POST /api/logout/`.

    Autentica con la sesión para que un logout cross-site sin token CSRF
    no pueda cerrar la sesión de otra persona.
    """

    authentication_classes = [SessionUserAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        end_user_session(request)
        return Response({"ok": True})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SessionView(APIView):
    """`GET /api/session/`. También entrega el token CSRF (cookie y body) al
    SPA, aunque todavía no haya sesión."""

    authentication_classes = [SessionUserAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        if not isinstance(request.user, User):
            return Response(
                {"error": "Unauthorized", **csrf_token_payload(request)}, status=401
            )
        return Response(_session_payload(request, request.user))
