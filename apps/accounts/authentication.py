"""Bridges `request.admin_session` (`AdminSessionMiddleware`, design
decision #5, `apps/accounts/sessions.py`) to `request.user` for DRF
permission classes such as `HasTorqueTrackPermission`.

Prerequisite added in Phase 6 (task 6.3), not Phase 3: Phase 3 built the
dual session-cookie middleware and the RBAC permission class, but
deliberately left the two disconnected because no admin login view existed
yet to populate a session with a `user_id` (see `apps/accounts/permissions.
py`'s module docstring). Phase 6's admin quote actions (convert/preview/
reopen/send) are the first endpoints in this migration that actually need
`request.user` resolved from a real session cookie, so this bridge is added
here — mirroring Phase 5's precedent of adding a narrowly-scoped prerequisite
(the `ActivityLog` Stage A binding) in the phase that first needs it, not
the phase that conceptually "owns" the table/feature. The admin login view
itself (which would issue that session) remains out of scope; tests create
a session directly via `SessionStore`, exactly as a login view would.

`authenticate()` never returns `None` — even a missing/invalid session
resolves to `AnonymousUser`, so `request.successful_authenticator` is always
set. This makes `HasTorqueTrackPermission` failures always surface as 403
(matching `requirePermission()`'s legacy behavior: any failure — no
session, an inactive user, or a genuinely missing permission — is
`err("Forbidden", 403)`), instead of DRF's default of surfacing a missing
authenticator as 401.
"""

from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication

from apps.accounts.models import User


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

        return (user, None)
