"""Siembra de `authorization/0002_seed_roles`: los permisos del panel cuelgan
de los modelos de dominio (y de `Role` los dos sin modelo propio), el Role
`employee` tiene los 15 por defecto y `admin` es de acceso total.

Sin proveedores que mockear. Regla que se assertea a propósito: la copia
congelada del catálogo en la migración coincide con `STAFF_PERMISSIONS`, así
un permiso nuevo en el catálogo no queda sin sembrar en silencio.
"""
from importlib import import_module

import pytest
from django.contrib.auth.models import Group, Permission

from apps.authorization.models import Role
from apps.authorization.permissions import DEFAULT_EMPLOYEE_PERMISSIONS, STAFF_PERMISSIONS

SEED = import_module("apps.authorization.migrations.0002_seed_roles")


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
def test_panel_only_permissions_hang_off_the_role_model():
    pairs = set(
        Permission.objects.filter(codename__in=["manage_users", "view_dashboard"]).values_list(
            "content_type__app_label", "content_type__model", "codename"
        )
    )

    assert pairs == {
        ("authorization", "role", "manage_users"),
        ("authorization", "role", "view_dashboard"),
    }


def test_the_frozen_catalog_matches_the_live_catalog():
    assert [row[:4] for row in SEED.STAFF_PERMISSIONS] == [tuple(row) for row in STAFF_PERMISSIONS]
    assert SEED.DEFAULT_EMPLOYEE_PERMISSIONS == DEFAULT_EMPLOYEE_PERMISSIONS


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
    assert employee.full_access is False


@pytest.mark.django_db
def test_admin_role_has_full_access_and_no_stored_permissions():
    admin = Role.objects.get(slug="admin")

    assert admin.full_access is True
    assert admin.permissions.count() == 0


@pytest.mark.django_db
def test_no_django_group_is_seeded():
    # `User` no tiene `groups`: el Role es la única fuente de permisos.
    assert not Group.objects.exists()
