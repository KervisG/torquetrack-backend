"""El Role es la única fuente de permisos. Sin Role no hay panel, aunque el
usuario esté activo.
"""
import pytest
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.authorization.models import Role
from apps.authorization.permissions import (
    HasRolePermission,
    has_role_permission,
    is_staff_user,
)
from tests.factories import create_role, create_staff_user, create_user


class _TakePaymentView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "payments.take"

    def get(self, request):
        return Response({"ok": True})


class _AnyStaffView(APIView):
    permission_classes = [HasRolePermission]

    def get(self, request):
        return Response({"ok": True})


def _call(view, user=None):
    request = APIRequestFactory().get("/probe")
    if user is not None:
        force_authenticate(request, user=user)
    return view.as_view()(request)


@pytest.mark.django_db
def test_an_active_user_without_role_is_not_staff():
    customer = create_user("U_CUSTOMER")

    assert is_staff_user(customer) is False
    assert _call(_AnyStaffView, customer).status_code == 403


@pytest.mark.django_db
def test_an_inactive_user_with_role_is_not_staff():
    staff = create_staff_user("U_OFF", full_access=True, active=False)

    assert is_staff_user(staff) is False


@pytest.mark.django_db
def test_full_access_role_bypasses_the_specific_permission_check():
    owner = create_staff_user("U_OWNER", full_access=True)

    assert _call(_TakePaymentView, owner).status_code == 200


@pytest.mark.django_db
def test_role_without_the_permission_gets_403():
    staff = create_staff_user("U_PARTS", permissions=["products.view"])

    assert _call(_TakePaymentView, staff).status_code == 403
    assert has_role_permission(staff, "products.view") is True


@pytest.mark.django_db
def test_role_with_the_permission_is_allowed():
    staff = create_staff_user("U_CASHIER", permissions=["payments.take"])

    assert _call(_TakePaymentView, staff).status_code == 200


@pytest.mark.django_db
def test_seeded_employee_role_grants_its_default_permissions():
    staff = create_user("U_EMP", role=Role.objects.get(slug="employee"))

    assert has_role_permission(staff, "dashboard.view") is True
    assert has_role_permission(staff, "users.manage") is False


@pytest.mark.django_db
def test_unknown_permission_string_is_denied():
    staff = create_user("U_ANY", role=create_role("any", permissions=["orders.view"]))

    assert has_role_permission(staff, "orders.nope") is False


@pytest.mark.django_db
def test_unauthenticated_request_gets_the_same_403_as_a_missing_permission():
    response = _call(_TakePaymentView)

    assert response.status_code == 403
    assert response.data == {"error": "You do not have permission to perform this action."}
