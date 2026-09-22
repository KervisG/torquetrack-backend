"""Dos cookies de sesión: `tt_admin` y `tt_customer`.

Django's built-in `django.contrib.sessions.middleware.SessionMiddleware`
supports exactly ONE cookie name per process (it always reads
`settings.SESSION_COOKIE_NAME`). To get two independent, simultaneously
valid session scopes, each scope gets its own middleware and its own
request attribute (`request.admin_session` / `request.customer_session`),
both backed by Django's OWN database session engine
(`settings.SESSION_ENGINE`, normally
`django.contrib.sessions.backends.db.SessionStore`) — so session-row
storage, decoding, and expiry lookup are 100% Django-native, not
reimplemented. `_NamedCookieSessionMiddleware` is modeled directly on
`django.contrib.sessions.middleware.SessionMiddleware`; only the cookie
name and the request attribute are namespaced.

The 7-day expiry (design decision #5) comes from the global
`settings.SESSION_COOKIE_AGE` (see `config/settings/base.py`), the same
mechanism Django's own default expiry uses, rather than calling
`session.set_expiry()` unconditionally on every request:
`SessionBase.set_expiry()` writes a `_session_expiry` key into the
session data, which forces a DB write (and a "modified, not empty"
session) even for a request that never actually touches the session —
this would have silently un-expired, and re-issued a cookie for, a
request that presented an already-expired session key. Letting the
global default apply keeps a genuinely empty/expired session both
empty AND cookie-less.
"""

import time
from importlib import import_module

from django.conf import settings
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sessions.exceptions import SessionInterrupted
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.utils.deprecation import MiddlewareMixin
from django.utils.http import http_date


class _NamedCookieSessionMiddleware(MiddlewareMixin):
    """Shared session-cookie plumbing; subclasses only set `cookie_name`
    and `request_attr`."""

    cookie_name: str = ""
    request_attr: str = ""
    cookie_path = "/"
    cookie_samesite = "Lax"

    def __init__(self, get_response):
        super().__init__(get_response)
        engine = import_module(settings.SESSION_ENGINE)
        self.SessionStore = engine.SessionStore

    @property
    def cookie_secure(self):
        # Cookie segura solo fuera de DEBUG.
        return not settings.DEBUG

    def process_request(self, request):
        session_key = request.COOKIES.get(self.cookie_name)
        session = self.SessionStore(session_key)
        setattr(request, self.request_attr, session)

    def process_response(self, request, response):
        session = getattr(request, self.request_attr, None)
        try:
            accessed = session.accessed
            modified = session.modified
            empty = session.is_empty()
        except AttributeError:
            return response

        if self.cookie_name in request.COOKIES and empty:
            response.delete_cookie(
                self.cookie_name,
                path=self.cookie_path,
                samesite=self.cookie_samesite,
            )
            patch_vary_headers(response, ("Cookie",))
            return response

        if accessed:
            patch_vary_headers(response, ("Cookie",))

        if (modified or settings.SESSION_SAVE_EVERY_REQUEST) and not empty:
            max_age = session.get_expiry_age()
            expires = http_date(time.time() + max_age)
            if response.status_code < 500:
                try:
                    session.save()
                except UpdateError:
                    raise SessionInterrupted(
                        "The request's session was deleted before the "
                        "request completed. The user may have logged out "
                        "in a concurrent request, for example."
                    )
                response.set_cookie(
                    self.cookie_name,
                    session.session_key,
                    max_age=max_age,
                    expires=expires,
                    path=self.cookie_path,
                    secure=self.cookie_secure or None,
                    httponly=True,
                    samesite=self.cookie_samesite,
                )
        return response


class AdminSessionMiddleware(_NamedCookieSessionMiddleware):
    """Backs `request.admin_session`, cookie `tt_admin` — employees/admins
    (Stage A `apps.auth.models.User`)."""

    cookie_name = "tt_admin"
    request_attr = "admin_session"


class CustomerSessionMiddleware(_NamedCookieSessionMiddleware):
    """Backs `request.customer_session`, cookie `tt_customer` — storefront
    customers (Stage A `apps.customers.models.Customer`, design decision
    #5)."""

    cookie_name = "tt_customer"
    request_attr = "customer_session"


def revoke_admin_sessions(user_id: str) -> None:
    """Port de `delete from sessions where kind='admin' and subject_id=$1`.

    Lo llama `apps/auth/admin_services.py` al desactivar o borrar un empleado.

    `AdminSessionAuthentication` ya revalida `active=True` contra la fila en
    cada request, así que no es esto lo que corta el acceso de un empleado
    recién desactivado; borrar la fila evita que una reactivación posterior
    resucite una sesión vieja que debería haber muerto.

    Recorre las sesiones vivas en vez de filtrar por `user_id` en SQL porque
    `session_data` es un blob firmado y serializado, no columnas
    consultables. La tabla solo guarda sesiones activas de staff y clientes,
    y esto corre únicamente al desactivar o borrar un usuario.

    No toca la tabla `sessions` de tokens hasheados.
    """
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        if session.get_decoded().get("user_id") == user_id:
            session.delete()
