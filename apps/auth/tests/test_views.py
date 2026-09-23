"""`/api/register/`, `/api/login/`, `/api/logout/` y `/api/session/`.

Una sola cuenta y una sola cookie (`tt_session`) para clientes y staff. El
acceso al panel lo decide el Role, no el login. Los requests autenticados
que mutan exigen el token CSRF.
"""
import pytest
from django.contrib.auth.hashers import check_password
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.auth.models import User
from apps.auth.utils.throttling import (
    LoginAccountRateThrottle,
    LoginRateThrottle,
    RegisterRateThrottle,
)
from apps.customers.models import Customer
from tests.factories import (
    DEFAULT_PASSWORD,
    create_customer,
    create_role,
    create_staff_user,
    create_user,
    session_client,
)

STRONG_PASSWORD = "Diesel-Torque-2026!"


@pytest.fixture(autouse=True)
def _clear_throttle_history():
    """`SimpleRateThrottle` guarda los intentos en el cache compartido del
    proceso, así que sin esto un test filtra su cuota al siguiente."""
    cache.clear()
    yield
    cache.clear()


def _register_payload(**overrides):
    payload = {
        "email": "Pat.Fleet@Example.com",
        "password": STRONG_PASSWORD,
        "name": "Pat Fleet",
        "company": "Fleet LLC",
        "phone": "555-0100",
    }
    payload.update(overrides)
    return payload


# --- register -----------------------------------------------------------------


@pytest.mark.django_db
def test_register_creates_a_customer_account_without_role_and_starts_a_session():
    response = APIClient().post("/api/register/", _register_payload(), format="json")

    assert response.status_code == 201
    body = response.json()
    assert body["authenticated"] is True
    assert body["user"]["email"] == "pat.fleet@example.com"
    assert body["user"]["firstName"] == "Pat"
    assert body["user"]["lastName"] == "Fleet"
    assert body["user"]["isStaff"] is False
    assert body["user"]["role"] is None
    assert body["user"]["permissions"] == []

    user = User.objects.get(email="pat.fleet@example.com")
    assert user.role is None
    assert check_password(STRONG_PASSWORD, user.password_hash)
    customer = Customer.objects.get(user=user)
    assert customer.email == "pat.fleet@example.com"
    assert customer.data["name"] == "Pat Fleet"
    assert customer.data["company"] == "Fleet LLC"
    assert customer.data["phone"] == "555-0100"

    cookie = response.cookies["tt_session"]
    assert cookie["httponly"] is True
    assert Session.objects.get(session_key=cookie.value).get_decoded()["user_id"] == user.pk


@pytest.mark.django_db
def test_register_does_not_link_an_existing_guest_customer_with_the_same_email():
    guest = create_customer("C_GUEST", email="pat.fleet@example.com")

    response = APIClient().post("/api/register/", _register_payload(), format="json")

    assert response.status_code == 201
    user = User.objects.get(email="pat.fleet@example.com")
    assert Customer.objects.get(user=user).pk != guest.pk
    guest.refresh_from_db()
    assert guest.user is None


@pytest.mark.django_db
def test_register_returns_409_for_an_existing_account_email():
    create_user("U_EXISTING", email="pat.fleet@example.com")

    response = APIClient().post("/api/register/", _register_payload(), format="json")

    assert response.status_code == 409
    assert response.json() == {"error": "Email already exists"}
    assert Customer.objects.count() == 0


@pytest.mark.django_db
def test_register_rejects_a_weak_password_with_the_django_validators():
    response = APIClient().post(
        "/api/register/", _register_payload(password="12345678"), format="json"
    )

    assert response.status_code == 400
    assert "error" in response.json()
    assert not User.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [{"email": "not-an-email"}, {"email": ""}, {"password": ""}, {"name": ""}],
)
def test_register_returns_400_for_missing_or_invalid_fields(overrides):
    response = APIClient().post(
        "/api/register/", _register_payload(**overrides), format="json"
    )

    assert response.status_code == 400
    assert not User.objects.exists()


@pytest.mark.django_db
def test_register_ignores_role_and_staff_fields_in_the_body():
    create_role("owner", full_access=True)

    response = APIClient().post(
        "/api/register/",
        _register_payload(role="owner", isStaff=True, id="U_CHOSEN"),
        format="json",
    )

    assert response.status_code == 201
    user = User.objects.get(email="pat.fleet@example.com")
    assert user.role is None
    assert user.pk != "U_CHOSEN"


@pytest.mark.django_db
def test_register_is_rate_limited_by_ip(monkeypatch):
    monkeypatch.setattr(RegisterRateThrottle, "rate", "2/min", raising=False)
    client = APIClient()

    for index in range(2):
        client.post(
            "/api/register/", _register_payload(email=f"a{index}@example.com"), format="json"
        )
    blocked = client.post(
        "/api/register/", _register_payload(email="a9@example.com"), format="json"
    )

    assert blocked.status_code == 429


# --- login --------------------------------------------------------------------


@pytest.mark.django_db
def test_login_returns_401_for_unknown_email():
    response = APIClient().post(
        "/api/login/", {"email": "nobody@example.com", "password": DEFAULT_PASSWORD}, format="json"
    )

    assert response.status_code == 401
    assert response.json() == {"error": "Incorrect email or password"}


@pytest.mark.django_db
def test_login_returns_401_for_wrong_password():
    create_user("U_BAD", email="employee@example.com", password=DEFAULT_PASSWORD)

    response = APIClient().post(
        "/api/login/", {"email": "employee@example.com", "password": "wrong"}, format="json"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_login_returns_401_for_inactive_user():
    create_user("U_OFF", email="off@example.com", password=DEFAULT_PASSWORD, active=False)

    response = APIClient().post(
        "/api/login/", {"email": "off@example.com", "password": DEFAULT_PASSWORD}, format="json"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_login_returns_401_for_empty_body():
    response = APIClient().post("/api/login/", {}, format="json")

    assert response.status_code == 401


@pytest.mark.django_db
def test_login_does_not_crash_on_an_unusable_password_hash():
    User.objects.create(id="U_BROKEN", email="broken@example.com", password_hash="")

    response = APIClient().post(
        "/api/login/", {"email": "broken@example.com", "password": DEFAULT_PASSWORD}, format="json"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_login_accepts_a_customer_and_sets_the_session_cookie():
    create_user(
        "U_CUSTOMER",
        email="pat@example.com",
        password=DEFAULT_PASSWORD,
        first_name="Pat",
        last_name="Fleet",
    )

    response = APIClient().post(
        "/api/login/", {"email": "PAT@example.com ", "password": DEFAULT_PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "user": {
            "id": "U_CUSTOMER",
            "email": "pat@example.com",
            "firstName": "Pat",
            "lastName": "Fleet",
            "isStaff": False,
            "role": None,
            "permissions": [],
        },
    }
    cookie = response.cookies["tt_session"]
    assert cookie.value
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert "tt_admin" not in response.cookies
    assert "tt_customer" not in response.cookies


@pytest.mark.django_db
def test_login_reports_role_and_permissions_for_staff():
    role = create_role(
        "sales", name="Sales", permissions=["dashboard.view", "orders.view"]
    )
    create_user("U_STAFF", email="sales@example.com", password=DEFAULT_PASSWORD, role=role)

    response = APIClient().post(
        "/api/login/", {"email": "sales@example.com", "password": DEFAULT_PASSWORD}, format="json"
    )

    user = response.json()["user"]
    assert user["isStaff"] is True
    assert user["role"] == {"slug": "sales", "name": "Sales", "fullAccess": False}
    assert sorted(user["permissions"]) == ["dashboard.view", "orders.view"]


@pytest.mark.django_db
def test_login_rotates_a_preexisting_session_key():
    create_user("U_FIX", email="fix@example.com", password=DEFAULT_PASSWORD)
    client, fixated_key = session_client("U_FIX")

    response = client.post(
        "/api/login/", {"email": "fix@example.com", "password": DEFAULT_PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert response.cookies["tt_session"].value != fixated_key
    assert not Session.objects.filter(session_key=fixated_key).exists()


@pytest.mark.django_db
def test_login_is_rate_limited_by_ip(monkeypatch):
    # `SimpleRateThrottle.THROTTLE_RATES` se resuelve al importar la clase, así
    # que se fija `rate` directamente.
    monkeypatch.setattr(LoginRateThrottle, "rate", "3/min", raising=False)
    create_user("U_THROTTLE", email="t@example.com", password=DEFAULT_PASSWORD)
    client = APIClient()

    for _ in range(3):
        assert (
            client.post(
                "/api/login/", {"email": "t@example.com", "password": "wrong"}, format="json"
            ).status_code
            == 401
        )

    blocked = client.post(
        "/api/login/", {"email": "t@example.com", "password": DEFAULT_PASSWORD}, format="json"
    )

    assert blocked.status_code == 429


@pytest.mark.django_db
def test_login_ip_throttle_ignores_a_rotating_x_forwarded_for(monkeypatch):
    monkeypatch.setattr(LoginRateThrottle, "rate", "3/min", raising=False)
    monkeypatch.setattr(LoginAccountRateThrottle, "rate", "1000/min", raising=False)
    client = APIClient()

    for index in range(3):
        response = client.post(
            "/api/login/",
            {"email": "x@example.com", "password": "wrong"},
            format="json",
            HTTP_X_FORWARDED_FOR=f"198.51.100.{index}",
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/login/",
        {"email": "x@example.com", "password": "wrong"},
        format="json",
        HTTP_X_FORWARDED_FOR="198.51.100.99",
    )

    assert blocked.status_code == 429


@pytest.mark.django_db
def test_login_ip_throttle_counts_each_trusted_client_ip_separately(monkeypatch, settings):
    settings.CLIENT_IP_HEADER = "HTTP_CF_CONNECTING_IP"
    monkeypatch.setattr(LoginRateThrottle, "rate", "2/min", raising=False)
    monkeypatch.setattr(LoginAccountRateThrottle, "rate", "1000/min", raising=False)
    client = APIClient()

    def attempt(client_ip):
        return client.post(
            "/api/login/",
            {"email": "cf@example.com", "password": "wrong"},
            format="json",
            HTTP_CF_CONNECTING_IP=client_ip,
        ).status_code

    assert attempt("203.0.113.1") == 401
    assert attempt(" 203.0.113.1 ") == 401
    assert attempt("203.0.113.1") == 429
    assert attempt("203.0.113.2") == 401


@pytest.mark.django_db
def test_login_account_throttle_blocks_the_same_email_from_different_ips(
    monkeypatch, settings
):
    settings.CLIENT_IP_HEADER = "HTTP_CF_CONNECTING_IP"
    monkeypatch.setattr(LoginRateThrottle, "rate", "1000/min", raising=False)
    monkeypatch.setattr(LoginAccountRateThrottle, "rate", "3/min", raising=False)
    create_user("U_ACCT", email="employee@example.com", password=DEFAULT_PASSWORD)
    client = APIClient()

    def attempt(identifier, client_ip, password="wrong"):
        return client.post(
            "/api/login/",
            {"email": identifier, "password": password},
            format="json",
            HTTP_CF_CONNECTING_IP=client_ip,
        ).status_code

    assert attempt("employee@example.com", "203.0.113.1") == 401
    assert attempt(" Employee@Example.com ", "203.0.113.2") == 401
    assert attempt("EMPLOYEE@EXAMPLE.COM", "203.0.113.3") == 401
    assert attempt("employee@example.com", "203.0.113.4", password=DEFAULT_PASSWORD) == 429
    assert attempt("other@example.com", "203.0.113.5") == 401


@pytest.mark.django_db
def test_login_account_throttle_skips_requests_without_an_identifier(monkeypatch):
    monkeypatch.setattr(LoginRateThrottle, "rate", "1000/min", raising=False)
    monkeypatch.setattr(LoginAccountRateThrottle, "rate", "1/min", raising=False)
    client = APIClient()

    for _ in range(3):
        response = client.post("/api/login/", {"password": "wrong"}, format="json")
        assert response.status_code == 401


# --- session ------------------------------------------------------------------


@pytest.mark.django_db
def test_session_returns_401_without_a_cookie_but_issues_a_csrf_cookie():
    response = APIClient().get("/api/session/")

    assert response.status_code == 401
    assert response.json() == {"error": "Unauthorized"}
    assert response.cookies["csrftoken"].value


@pytest.mark.django_db
def test_session_reports_every_catalog_permission_for_full_access():
    create_staff_user("U_OWNER", full_access=True)
    client, _ = session_client("U_OWNER")

    response = client.get("/api/session/")

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["isStaff"] is True
    assert user["role"]["fullAccess"] is True
    assert "users.manage" in user["permissions"]
    assert len(user["permissions"]) == 26


@pytest.mark.django_db
def test_session_returns_401_after_the_user_is_deactivated():
    create_user("U_SESS_OFF")
    client, _ = session_client("U_SESS_OFF")
    User.objects.filter(pk="U_SESS_OFF").update(active=False)

    response = client.get("/api/session/")

    assert response.status_code == 401


# --- logout -------------------------------------------------------------------


@pytest.mark.django_db
def test_logout_deletes_the_session_row_and_clears_the_cookie():
    create_user("U_LOGOUT")
    client, session_key = session_client("U_LOGOUT")

    response = client.post("/api/logout/")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not Session.objects.filter(session_key=session_key).exists()
    assert response.cookies["tt_session"].value == ""


@pytest.mark.django_db
def test_logout_returns_200_without_a_session():
    response = APIClient().post("/api/logout/")

    assert response.status_code == 200


# --- CSRF ---------------------------------------------------------------------


@pytest.mark.django_db
def test_authenticated_unsafe_request_without_csrf_token_is_rejected():
    create_user("U_CSRF")
    client, session_key = session_client("U_CSRF", enforce_csrf=True)

    response = client.post("/api/logout/")

    assert response.status_code == 403
    assert Session.objects.filter(session_key=session_key).exists()


@pytest.mark.django_db
def test_authenticated_unsafe_request_with_csrf_token_is_accepted():
    create_user("U_CSRF_OK")
    client, _ = session_client("U_CSRF_OK", enforce_csrf=True)
    token = client.get("/api/session/").cookies["csrftoken"].value

    response = client.post("/api/logout/", HTTP_X_CSRFTOKEN=token)

    assert response.status_code == 200


# --- rutas retiradas ----------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/api/admin/login/", "/api/admin/logout/", "/api/admin/session/"]
)
def test_admin_specific_auth_routes_no_longer_exist(path):
    # Se valida con el resolver porque la página 404 de Django falla al
    # renderizar en este entorno (bug de `Context.__copy__` con Python 3.14).
    with pytest.raises(Resolver404):
        resolve(path)
