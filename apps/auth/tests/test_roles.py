"""Roles de staff: siembra de Admin/Employee y chequeo por Role."""
import pytest
from django.contrib.auth.models import Permission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.auth.models import EmployeeRole, Role, User
from apps.auth.permissions import HasTorqueTrackPermission, has_torquetrack_permission


class _TakePaymentView(APIView):
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "payments.take"

    def get(self, request):
        return Response({"ok": True})


def _make_user(user_id, role="authorized", permissions=None):
    return User(
        id=user_id,
        username=f"{user_id}@example.com",
        password_hash="scrypt$salt$hash",
        role=role,
        active=True,
        permissions=permissions or [],
    )


@pytest.mark.django_db
def test_seed_creates_admin_and_employee_roles():
    admin = Role.objects.get(slug="admin")
    employee = Role.objects.get(slug="employee")

    assert admin.full_access is True
    assert employee.full_access is False
    assert employee.permissions.filter(
        content_type__app_label="backoffice", codename="view_dashboard"
    ).exists()
    assert employee.permissions.filter(
        content_type__app_label="tt_auth", codename="manage_users"
    ).exists() is False


@pytest.mark.django_db
def test_assigned_role_grants_permission_missing_from_jsonb():
    role = Role.objects.get(slug="employee")
    user = _make_user("usr_role_grant", permissions=[])
    EmployeeRole.objects.create(user_id=user.pk, role=role)

    request = APIRequestFactory().get("/take-payment")
    force_authenticate(request, user=user)

    response = _TakePaymentView.as_view()(request)

    assert response.status_code == 200


@pytest.mark.django_db
def test_assigned_role_denies_permission_even_if_jsonb_has_it():
    content_perm = Permission.objects.get(
        content_type__app_label="catalog",
        content_type__model="product",
        codename="view_product",
    )
    role = Role.objects.create(name="Catalog only", slug="catalog-only")
    role.permissions.add(content_perm)
    user = _make_user("usr_role_deny", permissions=["payments.take"])
    EmployeeRole.objects.create(user_id=user.pk, role=role)

    request = APIRequestFactory().get("/take-payment")
    force_authenticate(request, user=user)

    response = _TakePaymentView.as_view()(request)

    assert response.status_code == 403
    assert has_torquetrack_permission(user, "products.view") is True
