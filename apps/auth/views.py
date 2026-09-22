"""`admin/login`, `admin/logout` y `admin/session`."""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.permissions import is_active_admin_user
from apps.auth.authentication import AdminSessionAuthentication
from apps.auth.services import (
    authenticate_admin_user,
    register_user,
    serialize_admin_session_user,
)
from apps.auth.utils.throttling import AdminLoginRateThrottle, RegisterRateThrottle


class AdminLoginView(APIView):
    """`POST /api/admin/login/`."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AdminLoginRateThrottle]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        email = body.get("email") or body.get("username")
        user = authenticate_admin_user(email, body.get("password"))
        if user is None:
            return Response({"error": "Incorrect email or password"}, status=401)

        session = request.admin_session
        # `flush()` descarta la session key que el cliente ya traía, para que
        # un token fijado de antemano por un tercero no quede promovido a
        # sesión autenticada.
        session.flush()
        session["user_id"] = user.pk
        return Response(
            {
                "ok": True,
                "user": {
                    "id": user.pk,
                    "email": user.username,
                    "username": user.username,
                    "role": user.role,
                },
            }
        )


class RegisterView(APIView):
    """`POST /api/register/`."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [RegisterRateThrottle]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        result = register_user(body)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminLogoutView(APIView):
    """`POST /api/admin/logout/`."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        request.admin_session.flush()
        return Response({"ok": True})


class AdminSessionView(APIView):
    """`GET /api/admin/session/`."""

    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        if not is_active_admin_user(request.user):
            return Response({"error": "Unauthorized"}, status=401)
        return Response(
            {"authenticated": True, "user": serialize_admin_session_user(request.user)}
        )
