"""`GET /api/health/`, la que pinga el hosting para saber si el proceso sirve.

Pública, sin autenticación ni throttle: la llama un chequeo automático que no
tiene sesión y que no puede quedar bloqueado por una cuota. No devuelve datos,
solo si la base responde. En producción está exenta del redirect a HTTPS
(`SECURE_REDIRECT_EXEMPT` en `config/settings/prod.py`).
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.health.services import database_is_available

DATABASE_UNAVAILABLE = "Database unavailable"


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        if not database_is_available():
            return Response({"ok": False, "error": DATABASE_UNAVAILABLE}, status=503)
        return Response({"ok": True})
