import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.authentication.models import User
from apps.authentication.utils.throttling import (
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
    guest_cart_client,
    session_client,
)

STRONG_PASSWORD = "Diesel-Torque-2026!"


@pytest.fixture(autouse=True)
def _clear_throttle_history(db):
    """`SimpleRateThrottle` guarda los intentos en el cache compartido
    (`DatabaseCache`, tabla `django_cache`), así que sin esto un test filtra
    su cuota al siguiente. Pide `db` porque el cache es una tabla."""
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


REGISTERED = {"ok": True, "message": "Check your email to verify your account."}


@pytest.mark.django_db
def test_register_creates_a_customer_account_without_role_and_no_session():
    client = APIClient()
    response = client.post("/api/register/", _register_payload(), format="json")

    assert response.status_code == 201
    assert response.json() == REGISTERED

    user = User.objects.get(email="pat.fleet@example.com")
    assert user.role is None
    assert user.first_name == "Pat"
    assert user.last_name == "Fleet"
    assert user.check_password(STRONG_PASSWORD)
    customer = Customer.objects.get(user=user)
    assert customer.email == "pat.fleet@example.com"
    assert customer.data["name"] == "Pat Fleet"
    assert customer.data["company"] == "Fleet LLC"
    assert customer.data["phone"] == "555-0100"

    # Sin sesión: si el registro nuevo la abriera, el de un email ya
    # registrado respondería distinto y revelaría qué correos tienen cuenta.
    assert settings.SESSION_COOKIE_NAME not in response.cookies
    assert client.get("/api/session/").status_code == 401


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
def test_register_answers_an_existing_account_email_like_a_new_one():
    create_user("U_EXISTING", email="pat.fleet@example.com", password=DEFAULT_PASSWORD)

    existing = APIClient().post("/api/register/", _register_payload(), format="json")
    fresh = APIClient().post(
        "/api/register/", _register_payload(email="brand.new@example.com"), format="json"
    )

    assert existing.status_code == fresh.status_code == 201
    assert existing.json() == fresh.json() == REGISTERED
    assert settings.SESSION_COOKIE_NAME not in existing.cookies
    assert User.objects.filter(email="pat.fleet@example.com").count() == 1
    assert User.objects.get(pk="U_EXISTING").check_password(DEFAULT_PASSWORD)
    assert not Customer.objects.filter(email="pat.fleet@example.com").exists()


@pytest.mark.django_db
def test_register_with_an_existing_email_still_hashes_the_password(monkeypatch):
    """El hash de relleno iguala el tiempo de respuesta de los dos casos."""
    create_user("U_EXISTING", email="pat.fleet@example.com")
    hashed = []
    real_set_password = User.set_password

    def spy(self, raw_password):
        hashed.append(raw_password)
        return real_set_password(self, raw_password)

    monkeypatch.setattr(User, "set_password", spy)

    APIClient().post("/api/register/", _register_payload(), format="json")

    assert hashed == [STRONG_PASSWORD]


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
    User.objects.create(id="U_BROKEN", email="broken@example.com", password="")

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
    body = response.json()
    assert isinstance(body.pop("csrfToken"), str)
    assert body == {
        "authenticated": True,
        "user": {
            "id": "U_CUSTOMER",
            "email": "pat@example.com",
            "firstName": "Pat",
            "lastName": "Fleet",
            "isStaff": False,
            "role": None,
            "permissions": [],
            "emailVerified": False,
        },
    }
    cookie = response.cookies[settings.SESSION_COOKIE_NAME]
    assert cookie.value
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"


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
    # Fijación de sesión: un tercero planta una key anónima antes del login.
    # (Si la sesión ya es de ese mismo usuario, `login()` de Django la
    # conserva: no hay nada que un tercero pueda haber fijado.)
    create_user("U_FIX", email="fix@example.com", password=DEFAULT_PASSWORD)
    client = guest_cart_client("CART_FIXATED")
    fixated_key = client.cookies[settings.SESSION_COOKIE_NAME].value

    response = client.post(
        "/api/login/", {"email": "fix@example.com", "password": DEFAULT_PASSWORD}, format="json"
    )

    assert response.status_code == 200
    assert response.cookies[settings.SESSION_COOKIE_NAME].value != fixated_key
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
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    monkeypatch.setattr(LoginRateThrottle, "rate", "2/min", raising=False)
    monkeypatch.setattr(LoginAccountRateThrottle, "rate", "1000/min", raising=False)
    client = APIClient()

    def attempt(client_ip):
        return client.post(
            "/api/login/",
            {"email": "proxied@example.com", "password": "wrong"},
            format="json",
            HTTP_X_FORWARDED_FOR=client_ip,
        ).status_code

    assert attempt("203.0.113.1") == 401
    assert attempt(" 203.0.113.1 ") == 401
    assert attempt("203.0.113.1") == 429
    assert attempt("203.0.113.2") == 401


@pytest.mark.django_db
def test_login_account_throttle_blocks_the_same_email_from_different_ips(
    monkeypatch, settings
):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    monkeypatch.setattr(LoginRateThrottle, "rate", "1000/min", raising=False)
    monkeypatch.setattr(LoginAccountRateThrottle, "rate", "3/min", raising=False)
    create_user("U_ACCT", email="employee@example.com", password=DEFAULT_PASSWORD)
    client = APIClient()

    def attempt(identifier, client_ip, password="wrong"):
        return client.post(
            "/api/login/",
            {"email": identifier, "password": password},
            format="json",
            HTTP_X_FORWARDED_FOR=client_ip,
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


@pytest.mark.django_db
def test_login_account_throttle_blocks_after_twenty_failed_attempts(monkeypatch):
    monkeypatch.setattr(LoginRateThrottle, "rate", "1000/min", raising=False)
    monkeypatch.setattr(LoginAccountRateThrottle, "rate", "20/hour", raising=False)
    create_user("U_FAILS", email="fails@example.com", password=DEFAULT_PASSWORD)
    client = APIClient()

    for _ in range(20):
        response = client.post(
            "/api/login/", {"email": "fails@example.com", "password": "wrong"}, format="json"
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/login/", {"email": "fails@example.com", "password": DEFAULT_PASSWORD}, format="json"
    )

    assert blocked.status_code == 429
    assert int(blocked["Retry-After"]) > 0
    assert "error" in blocked.json()


@pytest.mark.django_db
def test_login_account_throttle_does_not_count_successful_logins(monkeypatch):
    monkeypatch.setattr(LoginRateThrottle, "rate", "1000/min", raising=False)
    monkeypatch.setattr(LoginAccountRateThrottle, "rate", "3/min", raising=False)
    create_user("U_OK", email="ok@example.com", password=DEFAULT_PASSWORD)

    for _ in range(6):
        response = APIClient().post(
            "/api/login/", {"email": "ok@example.com", "password": DEFAULT_PASSWORD}, format="json"
        )
        assert response.status_code == 200


@pytest.mark.django_db
def test_a_successful_login_resets_the_failed_attempts_of_the_account(monkeypatch):
    monkeypatch.setattr(LoginRateThrottle, "rate", "1000/min", raising=False)
    monkeypatch.setattr(LoginAccountRateThrottle, "rate", "3/min", raising=False)
    create_user("U_RESET", email="reset@example.com", password=DEFAULT_PASSWORD)
    client = APIClient()

    def attempt(password):
        return client.post(
            "/api/login/", {"email": "reset@example.com", "password": password}, format="json"
        ).status_code

    assert [attempt("wrong"), attempt("wrong")] == [401, 401]
    assert attempt(DEFAULT_PASSWORD) == 200
    # Sin el reinicio, el tercer fallo llegaría al tope y el cuarto sería 429.
    assert [attempt("wrong"), attempt("wrong"), attempt(DEFAULT_PASSWORD)] == [401, 401, 200]


@pytest.mark.django_db
def test_a_locked_account_does_not_block_another_account_from_the_same_ip(monkeypatch):
    monkeypatch.setattr(LoginRateThrottle, "rate", "5/min", raising=False)
    monkeypatch.setattr(LoginAccountRateThrottle, "rate", "2/min", raising=False)
    create_user("U_VICTIM", email="victim@example.com", password=DEFAULT_PASSWORD)
    create_user("U_OWNER", email="owner@example.com", password=DEFAULT_PASSWORD)
    client = APIClient()

    def attempt(email, password="wrong"):
        return client.post(
            "/api/login/", {"email": email, "password": password}, format="json"
        ).status_code

    assert [attempt("victim@example.com") for _ in range(3)] == [401, 401, 429]
    assert attempt("owner@example.com") == 401
    assert attempt("owner@example.com", DEFAULT_PASSWORD) == 200
    # La otra cuenta sigue sujeta al tope por IP, que cuenta todos los intentos.
    assert attempt("owner@example.com") == 429


# --- session ------------------------------------------------------------------


@pytest.mark.django_db
def test_session_returns_401_without_a_cookie_but_issues_a_csrf_token():
    response = APIClient().get("/api/session/")

    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "Unauthorized"
    assert isinstance(body["csrfToken"], str) and body["csrfToken"]
    assert response.cookies[settings.CSRF_COOKIE_NAME].value


@pytest.mark.django_db
def test_session_returns_the_csrf_token_when_authenticated():
    create_user("U_SESS_CSRF")
    client, _ = session_client("U_SESS_CSRF", enforce_csrf=True)

    response = client.get("/api/session/")

    assert response.status_code == 200
    token = response.json()["csrfToken"]
    assert client.post("/api/logout/", HTTP_X_CSRFTOKEN=token).status_code == 200


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
    assert response.cookies[settings.SESSION_COOKIE_NAME].value == ""


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
    token = client.get("/api/session/").json()["csrfToken"]

    response = client.post("/api/logout/", HTTP_X_CSRFTOKEN=token)

    assert response.status_code == 200


@pytest.mark.django_db
def test_login_returns_a_rotated_csrf_token_that_authorizes_the_next_mutation():
    create_user("U_CSRF_LOGIN", email="csrf.login@example.com", password=DEFAULT_PASSWORD)
    client = APIClient(enforce_csrf_checks=True)
    before = client.get("/api/session/").cookies[settings.CSRF_COOKIE_NAME].value

    response = client.post(
        "/api/login/",
        {"email": "csrf.login@example.com", "password": DEFAULT_PASSWORD},
        format="json",
    )

    assert response.status_code == 200
    token = response.json()["csrfToken"]
    assert response.cookies[settings.CSRF_COOKIE_NAME].value != before
    assert client.post("/api/logout/", HTTP_X_CSRFTOKEN=token).status_code == 200


# --- rutas retiradas ----------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/api/admin/login/", "/api/admin/logout/", "/api/admin/session/"]
)
def test_admin_specific_auth_routes_no_longer_exist(path):
    # Se valida con el resolver: la prueba es sobre el enrutado, no sobre la
    # página 404 que renderiza Django.
    with pytest.raises(Resolver404):
        resolve(path)
