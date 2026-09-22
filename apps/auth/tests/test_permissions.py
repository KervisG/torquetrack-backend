"""`HasTorqueTrackPermission`: admin pasa todo; empleado sin el permiso
recibe 403; con el permiso pasa.
"""
import pytest
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.auth.models import User
from apps.auth.permissions import HasTorqueTrackPermission


class _TakePaymentView(APIView):
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "payments.take"

    def get(self, request):
        return Response({"ok": True})


def _make_user(role, permissions):
    return User(
        id="usr_test",
        username="test.user",
        password_hash="scrypt$salt$hash",
        role=role,
        active=True,
        permissions=permissions,
    )


@pytest.mark.django_db
def test_admin_role_bypasses_the_specific_permission_check():
    request = APIRequestFactory().get("/take-payment")
    force_authenticate(request, user=_make_user("admin", []))

    response = _TakePaymentView.as_view()(request)

    assert response.status_code == 200


@pytest.mark.django_db
def test_non_admin_without_the_permission_gets_403():
    request = APIRequestFactory().get("/take-payment")
    force_authenticate(request, user=_make_user("authorized", ["products.view"]))

    response = _TakePaymentView.as_view()(request)

    assert response.status_code == 403


@pytest.mark.django_db
def test_non_admin_with_the_permission_is_allowed():
    request = APIRequestFactory().get("/take-payment")
    force_authenticate(request, user=_make_user("authorized", ["payments.take"]))

    response = _TakePaymentView.as_view()(request)

    assert response.status_code == 200


@pytest.mark.django_db
def test_unauthenticated_request_is_denied():
    request = APIRequestFactory().get("/take-payment")

    response = _TakePaymentView.as_view()(request)

    assert response.status_code in (401, 403)
