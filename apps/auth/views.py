"""`admin/login`, `admin/logout` y `admin/session`, port de
`app/api/admin/login|logout|session/route.ts`.

Las rutas conservan el prefijo `admin/` del contrato legado: el
`public/employee-login.html` que sigue en producción postea contra
`/api/admin/login` y no se puede mover sin romperlo.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import is_active_admin_user
from apps.auth.authentication import AdminSessionAuthentication
from apps.auth.services import authenticate_admin_user, serialize_admin_session_user
from apps.auth.throttling import AdminLoginRateThrottle


class AdminLoginView(APIView):
    """`POST /api/admin/login`, matching `app/api/admin/login/route.ts`.

    Primer endpoint que emite la cookie `tt_admin`: hasta ahora
    `AdminSessionMiddleware` y `HasTorqueTrackPermission` existían sin nadie
    que creara la sesión que ambos leen (ver el docstring de
    `apps/auth/authentication.py`).
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AdminLoginRateThrottle]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        user = authenticate_admin_user(body.get("username"), body.get("password"))
        if user is None:
            return Response({"error": "Incorrect username or password"}, status=401)

        session = request.admin_session
        # `flush()` descarta la session key que el cliente ya traía, para que
        # un token fijado de antemano por un tercero no quede promovido a
        # sesión autenticada.
        session.flush()
        session["user_id"] = user.pk
        # `AdminSessionMiddleware.process_response` persiste la sesión y emite
        # la cookie; la vista no escribe headers.
        return Response(
            {
                "ok": True,
                "user": {"id": user.pk, "username": user.username, "role": user.role},
            }
        )


class AdminLogoutView(APIView):
    """`POST /api/admin/logout`, matching `app/api/admin/logout/route.ts`."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # `flush()` borra la fila; el middleware elimina la cookie al ver la
        # sesión vacía. Responde 200 incluso sin sesión, como el original.
        request.admin_session.flush()
        return Response({"ok": True})


class AdminSessionView(APIView):
    """`GET /api/admin/session`, matching `app/api/admin/session/route.ts`."""

    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        if not is_active_admin_user(request.user):
            return Response({"error": "Unauthorized"}, status=401)
        return Response(
            {"authenticated": True, "user": serialize_admin_session_user(request.user)}
        )
