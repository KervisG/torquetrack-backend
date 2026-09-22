"""`admin/login`, `admin/logout`, `admin/session`, pinned against
`app/api/admin/login/route.ts`, `app/api/admin/logout/route.ts` and
`app/api/admin/session/route.ts`.

These are the first endpoints that ISSUE the `tt_admin` cookie; until now
`AdminSessionMiddleware` (task 3.2) and `AdminSessionAuthentication` (task
6.3) were only exercised by tests that built a `SessionStore` by hand.

Two guards here are deliberate deviations from the legacy contract rather
than ports of it, and both are asserted so a later refactor cannot silently
drop them: the login must NOT rehash a legacy scrypt row (doing so locks the
employee out of the still-live Next.js admin), and the login is rate
limited (the legacy route has no limit at all).
"""
import json
from importlib import import_module

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.auth.hashers import ScryptLegacyHasher
from apps.auth.throttling import AdminLoginRateThrottle

LEGACY_SALT = "0123456789abcdef0123456789abcdef"
PASSWORD = "diesel-pass-123"


@pytest.fixture(autouse=True)
def _clear_throttle_history():
    """`SimpleRateThrottle` guarda los intentos en el cache compartido del
    proceso, así que sin esto un test filtra su cuota al siguiente."""
    cache.clear()
    yield
    cache.clear()


def _legacy_hash(password=PASSWORD):
    """Hash con el formato `scrypt$salt$hash` que escribe `lib/auth.ts`."""
    return ScryptLegacyHasher().encode(password, LEGACY_SALT)


def _insert_user(
    user_id,
    username=None,
    password_hash=None,
    role="authorized",
    permissions=None,
    active=True,
    display_name=None,
):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into users (id, username, password_hash, role, active, "
            "permissions, display_name, created_at) "
            "values (%s, %s, %s, %s, %s, %s::jsonb, %s, now())",
            [
                user_id,
                username or f"{user_id}@example.com",
                password_hash if password_hash is not None else _legacy_hash(),
                role,
                active,
                json.dumps(permissions or []),
                display_name,
            ],
        )


def _session_client(user_id):
    engine = import_module(settings.SESSION_ENGINE)
    store = engine.SessionStore()
    store["user_id"] = user_id
    store.save()
    client = APIClient()
    client.cookies["tt_admin"] = store.session_key
    return client, store.session_key


# --- login ------------------------------------------------------------------


@pytest.mark.django_db
def test_login_returns_401_for_unknown_username():
    response = APIClient().post(
        "/api/admin/login/", {"username": "nobody", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 401
    assert response.json() == {"error": "Incorrect username or password"}


@pytest.mark.django_db
def test_login_returns_401_for_wrong_password():
    _insert_user("usr_login_bad", username="employee")

    response = APIClient().post(
        "/api/admin/login/", {"username": "employee", "password": "wrong"}, format="json"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_login_returns_401_for_inactive_user():
    _insert_user("usr_login_off", username="disabled", active=False)

    response = APIClient().post(
        "/api/admin/login/", {"username": "disabled", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_login_returns_401_for_empty_body():
    response = APIClient().post("/api/admin/login/", {}, format="json")

    assert response.status_code == 401


@pytest.mark.django_db
def test_login_does_not_crash_on_unusable_password_hash():
    """`verifyPassword` envuelve todo en try/catch; `identify_hasher` no."""
    _insert_user("usr_login_broken", username="broken", password_hash="")

    response = APIClient().post(
        "/api/admin/login/", {"username": "broken", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_login_accepts_legacy_scrypt_hash_and_sets_the_admin_cookie():
    _insert_user("usr_login_ok", username="employee", role="authorized")

    response = APIClient().post(
        "/api/admin/login/", {"username": "employee", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "user": {"id": "usr_login_ok", "username": "employee", "role": "authorized"},
    }
    cookie = response.cookies["tt_admin"]
    assert cookie.value
    assert cookie["httponly"] is True
    assert Session.objects.get(session_key=cookie.value).get_decoded() == {
        "user_id": "usr_login_ok"
    }


@pytest.mark.django_db
def test_login_matches_username_case_insensitively():
    _insert_user("usr_login_case", username="Employee")

    response = APIClient().post(
        "/api/admin/login/", {"username": "EMPLOYEE", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 200


@pytest.mark.django_db
def test_login_does_not_rehash_the_legacy_scrypt_row():
    """Un rehash a PBKDF2 dejaría el hash ilegible para `verifyPassword` de
    `lib/auth.ts` y expulsaría al empleado del admin de Next.js en
    producción."""
    stored = _legacy_hash()
    _insert_user("usr_login_keep", username="employee", password_hash=stored)

    response = APIClient().post(
        "/api/admin/login/", {"username": "employee", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert User.objects.get(pk="usr_login_keep").password_hash == stored


@pytest.mark.django_db
def test_login_rotates_a_preexisting_session_key():
    _insert_user("usr_login_fix", username="employee")
    client, fixated_key = _session_client("usr_login_fix")

    response = client.post(
        "/api/admin/login/", {"username": "employee", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert response.cookies["tt_admin"].value != fixated_key
    assert not Session.objects.filter(session_key=fixated_key).exists()


@pytest.mark.django_db
def test_login_is_rate_limited_by_ip(monkeypatch):
    # `SimpleRateThrottle.THROTTLE_RATES` se resuelve al importar la clase, así
    # que `override_settings(REST_FRAMEWORK=...)` no llega a tiempo; se fija
    # `rate` directamente, que es lo que `__init__` consulta primero.
    monkeypatch.setattr(AdminLoginRateThrottle, "rate", "3/min", raising=False)
    _insert_user("usr_login_throttle", username="employee")
    client = APIClient()

    for _ in range(3):
        assert (
            client.post(
                "/api/admin/login/", {"username": "employee", "password": "wrong"}, format="json"
            ).status_code
            == 401
        )

    blocked = client.post(
        "/api/admin/login/", {"username": "employee", "password": PASSWORD}, format="json"
    )

    assert blocked.status_code == 429


# --- session ----------------------------------------------------------------


@pytest.mark.django_db
def test_session_returns_401_without_a_cookie():
    response = APIClient().get("/api/admin/session/")

    assert response.status_code == 401
    assert response.json() == {"error": "Unauthorized"}


@pytest.mark.django_db
def test_session_reports_wildcard_permissions_for_the_admin_role():
    _insert_user("usr_sess_admin", username="owner", role="admin", display_name="Owner")
    client, _ = _session_client("usr_sess_admin")

    response = client.get("/api/admin/session/")

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "user": {
            "id": "usr_sess_admin",
            "username": "owner",
            "name": "Owner",
            "role": "admin",
            "permissions": ["*"],
        },
    }


@pytest.mark.django_db
def test_session_reports_the_stored_permissions_for_an_employee():
    _insert_user(
        "usr_sess_emp", username="employee", permissions=["dashboard.view", "orders.view"]
    )
    client, _ = _session_client("usr_sess_emp")

    response = client.get("/api/admin/session/")

    assert response.status_code == 200
    assert response.json()["user"]["permissions"] == ["dashboard.view", "orders.view"]


@pytest.mark.django_db
def test_session_falls_back_to_username_when_display_name_is_null():
    _insert_user("usr_sess_noname", username="employee", display_name=None)
    client, _ = _session_client("usr_sess_noname")

    response = client.get("/api/admin/session/")

    assert response.json()["user"]["name"] == "employee"


@pytest.mark.django_db
def test_session_returns_401_after_the_user_is_deactivated():
    _insert_user("usr_sess_off", username="employee")
    client, _ = _session_client("usr_sess_off")
    User.objects.filter(pk="usr_sess_off").update(active=False)

    response = client.get("/api/admin/session/")

    assert response.status_code == 401


# --- logout -----------------------------------------------------------------


@pytest.mark.django_db
def test_logout_deletes_the_session_row_and_clears_the_cookie():
    _insert_user("usr_logout", username="employee")
    client, session_key = _session_client("usr_logout")

    response = client.post("/api/admin/logout/")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not Session.objects.filter(session_key=session_key).exists()
    assert response.cookies["tt_admin"].value == ""


@pytest.mark.django_db
def test_logout_returns_200_without_a_session():
    response = APIClient().post("/api/admin/logout/")

    assert response.status_code == 200


# --- session revocation on deactivate/delete --------------------------------


@pytest.mark.django_db
def test_deactivating_an_employee_revokes_their_live_session():
    _insert_user("usr_revoker", username="owner", role="admin")
    _insert_user("usr_revoked", username="employee", permissions=["dashboard.view"])
    _, revoked_key = _session_client("usr_revoked")
    admin_client, admin_key = _session_client("usr_revoker")

    response = admin_client.put(
        "/api/admin/users/usr_revoked/", {"active": False}, format="json"
    )

    assert response.status_code == 200
    assert not Session.objects.filter(session_key=revoked_key).exists()
    # La sesión de quien ejecuta la acción no se toca.
    assert Session.objects.filter(session_key=admin_key).exists()


@pytest.mark.django_db
def test_deleting_an_employee_revokes_their_live_session():
    _insert_user("usr_deleter_auth", username="owner", role="admin")
    _insert_user("usr_deleted_auth", username="employee")
    _, deleted_key = _session_client("usr_deleted_auth")
    admin_client, _ = _session_client("usr_deleter_auth")

    response = admin_client.delete("/api/admin/users/usr_deleted_auth/")

    assert response.status_code == 200
    assert not Session.objects.filter(session_key=deleted_key).exists()
