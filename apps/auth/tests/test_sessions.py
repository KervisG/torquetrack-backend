"""Una sola cookie de sesión (`SESSION_COOKIE_NAME`) y la revocación por usuario."""
import pytest
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session

from apps.auth.sessions import revoke_user_sessions

SEVEN_DAYS_SECONDS = 7 * 24 * 60 * 60


def test_session_cookie_settings():
    # En desarrollo se usan los nombres por defecto de Django; producción
    # les agrega el prefijo `__Host-` (`tests/test_settings.py`).
    assert settings.SESSION_COOKIE_NAME == "sessionid"
    assert settings.CSRF_COOKIE_NAME == "csrftoken"
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.SESSION_COOKIE_AGE == SEVEN_DAYS_SECONDS


def test_the_split_admin_and_customer_middlewares_are_gone():
    assert not any("AdminSession" in item for item in settings.MIDDLEWARE)
    assert not any("CustomerSession" in item for item in settings.MIDDLEWARE)
    assert "django.contrib.sessions.middleware.SessionMiddleware" in settings.MIDDLEWARE


def _session_for(user_id):
    store = SessionStore()
    store["user_id"] = user_id
    store.save()
    return store.session_key


@pytest.mark.django_db
def test_revoke_user_sessions_removes_only_that_users_sessions():
    first = _session_for("U_TARGET")
    second = _session_for("U_TARGET")
    other = _session_for("U_OTHER")

    revoke_user_sessions("U_TARGET")

    assert not Session.objects.filter(session_key__in=[first, second]).exists()
    assert Session.objects.filter(session_key=other).exists()
