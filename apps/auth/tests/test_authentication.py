import pytest
from django.contrib.sessions.backends.db import SessionStore
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.auth.authentication import SessionUserAuthentication
from apps.auth.models import User
from tests.factories import create_staff_user, create_user


def _request_with_session(data):
    django_request = APIRequestFactory().get("/")
    session = SessionStore()
    session.update(data)
    django_request.session = session
    return Request(django_request)


@pytest.mark.django_db
def test_no_session_resolves_to_anonymous():
    user, _ = SessionUserAuthentication().authenticate(_request_with_session({}))

    assert user.is_anonymous


@pytest.mark.django_db
def test_session_with_unknown_user_id_resolves_to_anonymous():
    request = _request_with_session({"user_id": "does-not-exist"})

    user, _ = SessionUserAuthentication().authenticate(request)

    assert user.is_anonymous


@pytest.mark.django_db
def test_session_with_inactive_user_resolves_to_anonymous():
    create_user("U_INACTIVE", active=False)

    user, _ = SessionUserAuthentication().authenticate(
        _request_with_session({"user_id": "U_INACTIVE"})
    )

    assert user.is_anonymous


@pytest.mark.django_db
def test_session_with_active_user_id_resolves_to_that_user_with_its_role():
    create_staff_user("U_ACTIVE", full_access=True)

    user, _ = SessionUserAuthentication().authenticate(
        _request_with_session({"user_id": "U_ACTIVE"})
    )

    assert isinstance(user, User)
    assert user.pk == "U_ACTIVE"
    assert user.is_authenticated is True
    assert user.role.full_access is True
