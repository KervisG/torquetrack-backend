"""RED/GREEN evidence for `AdminSessionAuthentication` (Phase 6 task 6.3
prerequisite — see `apps/accounts/authentication.py` module docstring).
"""
import pytest
from django.db import connection
from rest_framework.test import APIRequestFactory

from apps.accounts.authentication import AdminSessionAuthentication
from apps.accounts.models import User


def _insert_user(user_id, role="authorized", permissions=None, active=True):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into users (id, username, password_hash, role, active, "
            "permissions) values (%s, %s, %s, %s, %s, %s::jsonb)",
            [user_id, f"{user_id}@example.com", "scrypt$salt$hash", role, active,
             "[]" if permissions is None else __import__("json").dumps(permissions)],
        )


@pytest.mark.django_db
def test_no_session_resolves_to_anonymous_but_authenticated():
    request = APIRequestFactory().get("/")
    request.admin_session = {}

    user, _ = AdminSessionAuthentication().authenticate(request)

    assert user.is_anonymous


@pytest.mark.django_db
def test_session_with_unknown_user_id_resolves_to_anonymous():
    request = APIRequestFactory().get("/")
    request.admin_session = {"user_id": "does-not-exist"}

    user, _ = AdminSessionAuthentication().authenticate(request)

    assert user.is_anonymous


@pytest.mark.django_db
def test_session_with_inactive_user_resolves_to_anonymous():
    _insert_user("usr_inactive", active=False)
    request = APIRequestFactory().get("/")
    request.admin_session = {"user_id": "usr_inactive"}

    user, _ = AdminSessionAuthentication().authenticate(request)

    assert user.is_anonymous


@pytest.mark.django_db
def test_session_with_active_user_id_resolves_to_that_user():
    _insert_user("usr_active", role="admin")
    request = APIRequestFactory().get("/")
    request.admin_session = {"user_id": "usr_active"}

    user, _ = AdminSessionAuthentication().authenticate(request)

    assert isinstance(user, User)
    assert user.pk == "usr_active"
