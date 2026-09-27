"""`python manage.py grant_role --email ... --role <slug|none>`.

Sin proveedores que mockear. Reglas que se assertean a propósito: el comando
nunca crea cuentas (la persona se registra antes en la tienda), solo cambia el
Role; `--role none` lo quita, salvo que sea el último usuario activo con
acceso total; y deja rastro en la bitácora.
"""
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.authentication.models import User
from tests.factories import (
    activity_count,
    create_role,
    create_staff_user,
    create_user,
    session_client,
)


def _run(**options):
    call_command("grant_role", **options)


@pytest.mark.django_db
def test_grants_the_admin_role_to_a_registered_account(capsys):
    create_user("U_OWNER", email="owner@example.com")

    _run(email=" Owner@Example.com ", role="admin")

    user = User.objects.get(pk="U_OWNER")
    assert user.role.slug == "admin"
    assert user.role.full_access is True
    assert "admin" in capsys.readouterr().out
    assert activity_count(action="USER_ROLE_GRANTED", entity_id="U_OWNER") == 1


@pytest.mark.django_db
def test_the_granted_role_applies_to_the_open_session():
    create_user("U_OWNER", email="owner@example.com")
    client, _ = session_client("U_OWNER")

    _run(email="owner@example.com", role="employee")

    session = client.get("/api/session/").json()["user"]
    assert session["isStaff"] is True
    assert session["role"]["slug"] == "employee"


@pytest.mark.django_db
def test_role_none_removes_the_role():
    create_staff_user("U_OWNER", full_access=True)
    create_staff_user("U_EMPLOYEE", permissions=["orders.view"], email="emp@example.com")

    _run(email="emp@example.com", role="none")

    assert User.objects.get(pk="U_EMPLOYEE").role is None


@pytest.mark.django_db
def test_never_creates_an_account():
    with pytest.raises(CommandError, match="sign up"):
        _run(email="ghost@example.com", role="admin")

    assert not User.objects.filter(email="ghost@example.com").exists()


@pytest.mark.django_db
def test_rejects_an_unknown_role():
    create_user("U_PAT", email="pat@example.com")

    with pytest.raises(CommandError, match="Unknown role"):
        _run(email="pat@example.com", role="does-not-exist")

    assert User.objects.get(pk="U_PAT").role is None


@pytest.mark.django_db
def test_rejects_an_invalid_email():
    with pytest.raises(CommandError, match="valid --email"):
        _run(email="not-an-email", role="admin")


@pytest.mark.django_db
def test_keeps_the_last_active_full_access_user():
    create_staff_user("U_OWNER", full_access=True, email="owner@example.com")

    with pytest.raises(CommandError, match="At least one active full access user"):
        _run(email="owner@example.com", role="none")

    assert User.objects.get(pk="U_OWNER").role.full_access is True


@pytest.mark.django_db
def test_does_not_touch_the_password_or_the_active_flag():
    create_user("U_PAT", email="pat@example.com", password="Pat-Own-Pass-2026!", active=False)
    create_role("parts-desk")

    _run(email="pat@example.com", role="parts-desk")

    user = User.objects.get(pk="U_PAT")
    assert user.role.slug == "parts-desk"
    assert user.active is False
    assert user.check_password("Pat-Own-Pass-2026!")
