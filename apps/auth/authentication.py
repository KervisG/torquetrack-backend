"""Puente de `request.admin_session` (`AdminSessionMiddleware`) hacia
`request.user` para las permission classes de DRF.

`authenticate()` nunca devuelve `None`: sin sesión o con sesión inválida
resuelve a `AnonymousUser`. Así `HasTorqueTrackPermission` responde 403
y no el 401 por defecto de DRF cuando falta autenticador.
"""

from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication

from apps.auth.models import User
from apps.auth.permissions import get_staff_role


class AdminSessionAuthentication(BaseAuthentication):
    def authenticate(self, request):
        session = getattr(request, "admin_session", None)
        user_id = session.get("user_id") if session is not None else None
        if not user_id:
            return (AnonymousUser(), None)

        try:
            user = User.objects.get(pk=user_id, active=True)
        except User.DoesNotExist:
            return (AnonymousUser(), None)

        get_staff_role(user)
        return (user, None)
