"""Sesión de Django (`django.contrib.auth`): una sola cookie
(`SESSION_COOKIE_NAME`) y cómo se cortan las sesiones sin borrar filas.

Rutas: `POST /api/login/` y `GET /api/session/` como sonda de "¿esta sesión
sigue autenticando?". Sin proveedores que mockear. Lo que se assertea a
propósito: cambiar la contraseña invalida las demás sesiones (session auth
hash), desactivar corta la sesión en el request siguiente, el carrito
sobrevive al `login()` y `check_password` sube un hash con menos iteraciones.
"""
import pytest
from django.conf import settings
from django.contrib.auth.hashers import PBKDF2PasswordHasher
from rest_framework.test import APIClient

from apps.authentication.models import User
from apps.authentication.services import change_password
from apps.cart.services import CART_SESSION_KEY
from tests.factories import DEFAULT_PASSWORD, create_user, guest_cart_client, session_client

SEVEN_DAYS_SECONDS = 7 * 24 * 60 * 60


def test_session_cookie_settings():
    # En desarrollo se usan los nombres por defecto de Django; producción
    # les agrega el prefijo `__Host-` (`tests/test_settings.py`).
    assert settings.SESSION_COOKIE_NAME == "sessionid"
    assert settings.CSRF_COOKIE_NAME == "csrftoken"
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.SESSION_COOKIE_AGE == SEVEN_DAYS_SECONDS


def test_the_split_admin_and_customer_middlewares_are_gone():
    assert not any("AdminSession" in item for item in settings.MIDDLEWARE)
    assert not any("CustomerSession" in item for item in settings.MIDDLEWARE)
    assert "django.contrib.sessions.middleware.SessionMiddleware" in settings.MIDDLEWARE
    assert "django.contrib.auth.middleware.AuthenticationMiddleware" in settings.MIDDLEWARE


def test_django_auth_uses_the_custom_user_and_the_default_backend():
    # Sin backend propio: `ModelBackend` solo autentica y los permisos salen
    # de `User.has_perm`.
    assert settings.AUTH_USER_MODEL == "authentication.User"
    assert settings.AUTHENTICATION_BACKENDS == ["django.contrib.auth.backends.ModelBackend"]


def _is_signed_in(client) -> bool:
    return client.get("/api/session/").status_code == 200


@pytest.mark.django_db
def test_changing_the_password_ends_every_other_session_of_the_user():
    user = create_user("U_PW", password=DEFAULT_PASSWORD)
    other = create_user("U_OTHER")
    first, _ = session_client("U_PW")
    second, _ = session_client("U_PW")
    bystander, _ = session_client(other.pk)

    change_password(user, "Brand-New-Diesel-2026!")

    assert not _is_signed_in(first)
    assert not _is_signed_in(second)
    assert _is_signed_in(bystander)


@pytest.mark.django_db
def test_deactivating_the_user_ends_the_session_on_the_next_request():
    create_user("U_OFF")
    client, _ = session_client("U_OFF")
    assert _is_signed_in(client)

    User.objects.filter(pk="U_OFF").update(active=False)

    assert not _is_signed_in(client)


@pytest.mark.django_db
def test_login_rotates_the_session_key_and_keeps_the_cart():
    create_user("U_CART", email="cart@example.com", password=DEFAULT_PASSWORD)
    client = guest_cart_client("CART_SESSION_1")
    guest_key = client.cookies[settings.SESSION_COOKIE_NAME].value

    response = client.post(
        "/api/login/", {"email": "cart@example.com", "password": DEFAULT_PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert client.cookies[settings.SESSION_COOKIE_NAME].value != guest_key
    assert client.session[CART_SESSION_KEY] == "CART_SESSION_1"


@pytest.mark.django_db
def test_check_password_upgrades_a_hash_with_fewer_iterations():
    class WeakerPBKDF2(PBKDF2PasswordHasher):
        iterations = 1000

    user = create_user("U_OLD_HASH")
    user.password = WeakerPBKDF2().encode(DEFAULT_PASSWORD, WeakerPBKDF2().salt())
    user.save(update_fields=["password"])

    assert user.check_password(DEFAULT_PASSWORD)

    user.refresh_from_db()
    algorithm, iterations, *_rest = user.password.split("$")
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) == PBKDF2PasswordHasher.iterations


@pytest.mark.django_db
def test_login_upgrades_the_stored_hash_too():
    class WeakerPBKDF2(PBKDF2PasswordHasher):
        iterations = 1000

    user = create_user("U_OLD_LOGIN", email="old@example.com")
    User.objects.filter(pk=user.pk).update(
        password=WeakerPBKDF2().encode(DEFAULT_PASSWORD, WeakerPBKDF2().salt())
    )

    response = APIClient().post(
        "/api/login/", {"email": "old@example.com", "password": DEFAULT_PASSWORD}, format="json"
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert int(user.password.split("$")[1]) == PBKDF2PasswordHasher.iterations
