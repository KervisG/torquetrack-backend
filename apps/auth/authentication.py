"""`authenticate()` nunca devuelve `None`: sin sesión válida resuelve a
`AnonymousUser`, así `HasTorqueTrackPermission` responde 403 y no el 401 por
defecto de DRF.

Con una sesión válida se exige CSRF en los métodos que mutan: la cookie viaja
sola en cualquier request cross-site, así que sin el token un sitio ajeno
podría actuar como el usuario.
"""

from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import SessionAuthentication

from apps.auth.models import User
from apps.auth.sessions import SESSION_USER_KEY


class SessionUserAuthentication(SessionAuthentication):
    def authenticate(self, request):
        session = getattr(request._request, "session", None)
        user_id = session.get(SESSION_USER_KEY) if session is not None else None
        if not user_id:
            return (AnonymousUser(), None)

        user = (
            User.objects.select_related("role")
            .filter(pk=user_id, active=True)
            .first()
        )
        if user is None:
            return (AnonymousUser(), None)

        self.enforce_csrf(request)
        return (user, None)
