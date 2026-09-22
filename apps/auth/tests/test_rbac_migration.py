"""Los permisos de staff viven en los modelos de dominio, no en un
marcador. El Role Employee y el grupo `employee_default` tienen los 15
por defecto.
"""
import pytest
from django.contrib.auth.models import Group, Permission

from apps.auth.models import Role
from apps.auth.permission_catalog import DEFAULT_ROLE_LEGACY, STAFF_PERMISSIONS


@pytest.mark.django_db
def test_staff_permissions_hang_off_domain_models():
    expected = {(app_label, model, codename) for _legacy, app_label, model, codename in STAFF_PERMISSIONS}
    found = set(
        Permission.objects.filter(
            content_type__app_label__in={item[1] for item in STAFF_PERMISSIONS},
        ).values_list("content_type__app_label", "content_type__model", "codename")
    )
    assert expected.issubset(found)
    assert len(STAFF_PERMISSIONS) == 26


@pytest.mark.django_db
def test_legacy_marker_content_type_is_gone():
    assert not Permission.objects.filter(
        content_type__app_label="tt_auth",
        content_type__model="torquetrackpermission",
    ).exists()


@pytest.mark.django_db
def test_employee_default_group_has_the_default_role_permissions():
    group = Group.objects.get(name="employee_default")
    pairs = set(group.permissions.values_list("content_type__app_label", "codename"))
    expected = {(app, code) for legacy, app, _model, code in STAFF_PERMISSIONS if legacy in DEFAULT_ROLE_LEGACY}
    assert pairs == expected
    assert group.permissions.count() == 15


@pytest.mark.django_db
def test_employee_role_has_the_default_permissions():
    employee = Role.objects.get(slug="employee")
    pairs = set(employee.permissions.values_list("content_type__app_label", "codename"))
    expected = {(app, code) for legacy, app, _model, code in STAFF_PERMISSIONS if legacy in DEFAULT_ROLE_LEGACY}
    assert pairs == expected
    assert Role.objects.get(slug="admin").full_access is True
