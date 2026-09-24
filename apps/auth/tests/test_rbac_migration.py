"""Los permisos de staff viven en los modelos de dominio, no en un
marcador. El Role Employee y el grupo `employee_default` tienen los 15
por defecto.
"""
from importlib import import_module

import pytest
from django.apps import apps as global_apps
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from apps.auth.models import Role
from apps.auth.permission_catalog import DEFAULT_EMPLOYEE_PERMISSIONS, STAFF_PERMISSIONS


@pytest.mark.django_db
def test_staff_permissions_hang_off_domain_models():
    expected = {
        (app_label, model, codename)
        for _code, app_label, model, codename in STAFF_PERMISSIONS
    }
    found = set(
        Permission.objects.filter(
            content_type__app_label__in={item[1] for item in STAFF_PERMISSIONS},
        ).values_list("content_type__app_label", "content_type__model", "codename")
    )
    assert expected.issubset(found)
    assert len(STAFF_PERMISSIONS) == 26


@pytest.mark.django_db
def test_torquetrackpermission_marker_content_type_is_gone():
    assert not Permission.objects.filter(
        content_type__app_label="tt_auth",
        content_type__model="torquetrackpermission",
    ).exists()


@pytest.mark.django_db
def test_employee_default_group_has_the_default_role_permissions():
    group = Group.objects.get(name="employee_default")
    pairs = set(group.permissions.values_list("content_type__app_label", "codename"))
    expected = {
        (app, code)
        for panel_code, app, _model, code in STAFF_PERMISSIONS
        if panel_code in DEFAULT_EMPLOYEE_PERMISSIONS
    }
    assert pairs == expected
    assert group.permissions.count() == 15


@pytest.mark.django_db
def test_employee_role_has_the_default_permissions():
    employee = Role.objects.get(slug="employee")
    pairs = set(employee.permissions.values_list("content_type__app_label", "codename"))
    expected = {
        (app, code)
        for panel_code, app, _model, code in STAFF_PERMISSIONS
        if panel_code in DEFAULT_EMPLOYEE_PERMISSIONS
    }
    assert pairs == expected
    assert Role.objects.get(slug="admin").full_access is True


@pytest.mark.django_db
def test_backoffice_permissions_move_to_their_new_owners_keeping_role_grants():
    # Simula una base que corrió `backoffice`: los dos permisos cuelgan de
    # `backoffice.activitylog` y un Role y un Group los tienen.
    migration = import_module("apps.auth.migrations.0011_move_backoffice_permissions")
    old_type = ContentType.objects.create(app_label="backoffice", model="activitylog")
    old_dashboard = Permission.objects.create(
        content_type=old_type, codename="view_dashboard", name="Can view dashboard"
    )
    old_activity = Permission.objects.create(
        content_type=old_type, codename="view_activitylog", name="Can view activity log"
    )
    role = Role.objects.create(name="Sales", slug="sales-backoffice")
    role.permissions.set([old_dashboard, old_activity])
    group = Group.objects.create(name="backoffice-group")
    group.permissions.set([old_dashboard])

    migration.move_backoffice_permissions(global_apps, None)

    assert not ContentType.objects.filter(app_label="backoffice").exists()
    assert set(
        role.permissions.values_list("content_type__app_label", "content_type__model", "codename")
    ) == {("tt_auth", "user", "view_dashboard"), ("audit", "activitylog", "view_activitylog")}
    assert set(group.permissions.values_list("content_type__app_label", "codename")) == {
        ("tt_auth", "view_dashboard")
    }
