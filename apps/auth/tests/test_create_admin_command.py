"""`python manage.py create_admin --email ... [--password ...]`.

Arranque del primer staff: crea el `User` o asciende uno existente al Role
`admin` (acceso total), con el email marcado como verificado. Es idempotente:
correrlo dos veces no duplica nada ni pisa la contraseña si no se pasa una.

Mocking: el prompt de contraseña se falsea en su call site,
`apps.auth.management.commands.create_admin.getpass`. No hay proveedores
externos: el comando no manda correos.
"""
import pytest
from django.contrib.auth.hashers import check_password
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.auth.models import AccountToken, Role, User
from apps.auth.services import issue_account_token
from tests.factories import create_role, create_user, session_client

STRONG_PASSWORD = "Diesel-Admin-Boot-2026!"


def _run(*args, **options):
    call_command("create_admin", *args, **options)


def _admin_role() -> Role:
    return Role.objects.get(slug="admin")


@pytest.fixture
def interactive(monkeypatch):
    """Simula una terminal que responde al prompt con `answers` en orden."""
    answers = []
    monkeypatch.setattr(
        "apps.auth.management.commands.create_admin.getpass", lambda prompt="": answers.pop(0)
    )
    monkeypatch.setattr(
        "apps.auth.management.commands.create_admin.sys.stdin.isatty", lambda: True
    )
    return answers


@pytest.mark.django_db
def test_creates_a_verified_admin_with_full_access():
    _run(email=" Owner@Example.com ", password=STRONG_PASSWORD)

    user = User.objects.select_related("role").get(email="owner@example.com")
    assert user.role.slug == "admin"
    assert user.role.full_access is True
    assert user.active is True
    assert user.email_verified_at is not None
    assert check_password(STRONG_PASSWORD, user.password_hash)


@pytest.mark.django_db
def test_prompts_for_the_password_when_it_is_omitted(interactive):
    interactive.extend([STRONG_PASSWORD, STRONG_PASSWORD])

    _run(email="owner@example.com")

    user = User.objects.get(email="owner@example.com")
    assert check_password(STRONG_PASSWORD, user.password_hash)


@pytest.mark.django_db
def test_prompt_rejects_mismatched_passwords(interactive):
    interactive.extend([STRONG_PASSWORD, "Something-Else-2026!"])

    with pytest.raises(CommandError, match="do not match"):
        _run(email="owner@example.com")

    assert not User.objects.filter(email="owner@example.com").exists()


@pytest.mark.django_db
def test_new_admin_without_password_and_without_terminal_fails(monkeypatch):
    monkeypatch.setattr(
        "apps.auth.management.commands.create_admin.sys.stdin.isatty", lambda: False
    )

    with pytest.raises(CommandError, match="--password"):
        _run(email="owner@example.com")

    assert not User.objects.filter(email="owner@example.com").exists()


@pytest.mark.django_db
def test_rejects_a_password_that_fails_the_django_validators():
    with pytest.raises(CommandError):
        _run(email="owner@example.com", password="12345678")

    assert not User.objects.filter(email="owner@example.com").exists()


@pytest.mark.parametrize("email", ["", "not-an-email"])
@pytest.mark.django_db
def test_rejects_an_invalid_email(email):
    with pytest.raises(CommandError, match="email"):
        _run(email=email, password=STRONG_PASSWORD)


@pytest.mark.django_db
def test_promotes_an_existing_customer_and_revokes_their_sessions():
    employee_role = create_role("counter", permissions=["orders.view"])
    user = create_user(
        "U_PAT", email="pat@example.com", password=STRONG_PASSWORD, role=employee_role
    )
    User.objects.filter(pk=user.pk).update(active=False)
    _, session_key = session_client("U_PAT")

    _run(email="pat@example.com")

    user.refresh_from_db()
    assert user.role_id == _admin_role().pk
    assert user.active is True
    assert user.email_verified_at is not None
    # Sin `--password` la contraseña no cambia.
    assert check_password(STRONG_PASSWORD, user.password_hash)
    # Cambiar el Role cierra las sesiones abiertas.
    assert not Session.objects.filter(session_key=session_key).exists()


@pytest.mark.django_db
def test_password_on_an_existing_user_replaces_it_and_invalidates_reset_links():
    user = create_user("U_PAT", email="pat@example.com", password="Old-Diesel-Pass-2026!")
    issue_account_token(user, AccountToken.PASSWORD_RESET)

    _run(email="pat@example.com", password=STRONG_PASSWORD)

    user.refresh_from_db()
    assert check_password(STRONG_PASSWORD, user.password_hash)
    # Un enlace de reset ya emitido no puede volver a pisar la contraseña nueva.
    assert AccountToken.objects.get(user=user).used_at is not None


@pytest.mark.django_db
def test_is_idempotent():
    _run(email="owner@example.com", password=STRONG_PASSWORD)
    first = User.objects.get(email="owner@example.com")
    _, session_key = session_client(first.pk)

    _run(email="owner@example.com")

    assert User.objects.filter(email="owner@example.com").count() == 1
    again = User.objects.get(email="owner@example.com")
    assert again.password_hash == first.password_hash
    assert again.email_verified_at == first.email_verified_at
    assert again.role_id == _admin_role().pk
    # Ya era admin: no hubo cambio de Role, la sesión sigue viva.
    assert Session.objects.filter(session_key=session_key).exists()


@pytest.mark.django_db
def test_refuses_to_use_an_admin_role_without_full_access():
    Role.objects.filter(slug="admin").update(full_access=False)

    with pytest.raises(CommandError, match="full access"):
        _run(email="owner@example.com", password=STRONG_PASSWORD)

    assert not User.objects.filter(email="owner@example.com").exists()
