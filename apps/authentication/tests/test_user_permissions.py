"""Permisos de `User` y el login con el `ModelBackend` por defecto.

Sin proveedores que mockear. Reglas que se assertean a propósito: los
permisos salen solo del Role (acceso total concede todo) y `User.has_perm`
nunca consulta a `ModelBackend`, que buscaría `user_permissions` y `groups`
que este `User` no tiene; `request.user` trae el Role en la misma consulta, y
`createsuperuser` crea la cuenta con el Role `admin` que siembran las
migraciones. Quién abre `/admin/` se prueba en
`apps/authorization/tests/test_django_admin.py`.
"""
import pytest
from django.contrib.auth import authenticate, get_user
from django.contrib.auth.backends import ModelBackend
from django.core.management import call_command
from django.test import RequestFactory

from apps.authentication.models import User
from tests.factories import DEFAULT_PASSWORD, create_staff_user, create_user, session_client


def _forbidden(*args, **kwargs):
    raise AssertionError("ModelBackend must not be asked for permissions")


@pytest.mark.django_db
def test_has_perm_never_asks_model_backend(monkeypatch, settings):
    settings.AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
    for name in ("has_perm", "has_module_perms", "get_all_permissions"):
        monkeypatch.setattr(ModelBackend, name, _forbidden)
    staff = create_staff_user("U_NO_BACKEND", permissions=["products.view"])

    assert staff.has_perm("catalog.view_product") is True
    assert staff.has_perm("checkout.take_payment") is False
    assert staff.has_perms(["catalog.view_product"]) is True
    assert staff.has_module_perms("catalog") is True
    assert staff.get_all_permissions() >= {"catalog.view_product"}


@pytest.mark.django_db
def test_request_user_brings_its_role_in_the_same_query(django_assert_num_queries):
    create_staff_user("U_REQUEST", permissions=["products.view"])
    client, _ = session_client("U_REQUEST")
    request = RequestFactory().get("/")
    request.session = client.session

    user = get_user(request)

    assert user.pk == "U_REQUEST"
    with django_assert_num_queries(0):
        assert user.role.full_access is False


@pytest.mark.django_db
def test_get_user_rejects_unknown_and_inactive_users():
    create_user("U_INACTIVE", active=False)

    assert ModelBackend().get_user("does-not-exist") is None
    assert ModelBackend().get_user("U_INACTIVE") is None


@pytest.mark.django_db
def test_authenticate_normalizes_the_email_and_rejects_inactive_accounts():
    create_user("U_LOGIN", email="pat@example.com", password=DEFAULT_PASSWORD)
    create_user("U_GONE", email="gone@example.com", password=DEFAULT_PASSWORD, active=False)

    assert authenticate(None, email=" Pat@Example.COM ", password=DEFAULT_PASSWORD).pk == "U_LOGIN"
    assert authenticate(None, email="gone@example.com", password=DEFAULT_PASSWORD) is None
    assert authenticate(None, email="pat@example.com", password="wrong") is None


@pytest.mark.django_db
def test_role_permissions_are_the_only_source_of_has_perm():
    staff = create_staff_user("U_PARTS", permissions=["products.view"])
    customer = create_user("U_CUSTOMER")

    assert staff.has_perm("catalog.view_product") is True
    assert staff.has_perm("checkout.take_payment") is False
    assert staff.has_module_perms("catalog") is True
    assert staff.has_module_perms("checkout") is False
    assert customer.has_perm("catalog.view_product") is False
    assert customer.has_module_perms("catalog") is False
    assert customer.get_all_permissions() == set()


@pytest.mark.django_db
def test_object_permissions_are_never_granted():
    owner = create_staff_user("U_OBJ_OWNER", full_access=True)

    assert owner.has_perm("catalog.view_product", obj=object()) is False
    assert owner.get_all_permissions(obj=object()) == set()


@pytest.mark.django_db
def test_full_access_grants_every_permission():
    owner = create_staff_user("U_OWNER", full_access=True)

    assert owner.has_perms(["checkout.refund_payment", "authorization.manage_users"]) is True
    assert owner.has_module_perms("authorization") is True
    assert "authorization.manage_users" in owner.get_all_permissions()


@pytest.mark.django_db
def test_an_inactive_full_access_user_has_no_permission():
    owner = create_staff_user("U_OFF_OWNER", full_access=True, active=False)

    assert owner.has_perm("checkout.refund_payment") is False
    assert owner.has_module_perms("checkout") is False
    assert owner.is_staff is False


@pytest.mark.django_db
def test_create_superuser_gets_the_seeded_full_access_role():
    user = User.objects.create_superuser(" Owner@Example.com ", DEFAULT_PASSWORD)

    assert user.email == "owner@example.com"
    assert user.role.slug == "admin"
    assert user.role.full_access is True
    assert user.is_superuser is True
    assert user.email_verified_at is not None
    assert user.check_password(DEFAULT_PASSWORD)


@pytest.mark.django_db
def test_createsuperuser_command_creates_a_full_access_admin(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "Diesel-Admin-Boot-2026!")

    call_command("createsuperuser", "--noinput", "--email", "boss@example.com", verbosity=0)

    user = User.objects.get(email="boss@example.com")
    assert user.role.full_access is True
    assert user.is_staff is True
    assert user.check_password("Diesel-Admin-Boot-2026!")
