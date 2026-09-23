"""`POST /api/activate/`: el invitado que recibió el enlace del portal crea
su cuenta (User sin Role) con el email del Customer y queda vinculado.
"""
import hashlib

import pytest
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auth.models import User
from apps.auth.utils.throttling import ActivateRateThrottle
from apps.customers.models import Customer
from tests.factories import create_customer, create_user

TOKEN = "a" * 64
STRONG_PASSWORD = "Diesel-Torque-2026!"


@pytest.fixture(autouse=True)
def _clear_throttle_history():
    cache.clear()
    yield
    cache.clear()


def _invited_customer(customer_id="C_GUEST", email="guest@example.com", expires_in_days=7):
    return create_customer(
        customer_id,
        email=email,
        data={"name": "Guest Buyer"},
        activation_token_hash=hashlib.sha256(TOKEN.encode()).hexdigest(),
        activation_expires_at=timezone.now() + timezone.timedelta(days=expires_in_days),
    )


@pytest.mark.django_db
def test_activate_creates_a_user_links_the_customer_and_starts_a_session():
    _invited_customer()

    response = APIClient().post(
        "/api/activate/", {"token": TOKEN, "password": STRONG_PASSWORD}, format="json"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["authenticated"] is True
    assert body["user"]["email"] == "guest@example.com"
    assert body["user"]["isStaff"] is False

    user = User.objects.get(email="guest@example.com")
    assert user.role is None
    assert check_password(STRONG_PASSWORD, user.password_hash)
    customer = Customer.objects.get(pk="C_GUEST")
    assert customer.user == user
    assert customer.activation_token_hash is None
    assert customer.activation_expires_at is None
    assert response.cookies[settings.SESSION_COOKIE_NAME].value
    assert isinstance(body["csrfToken"], str) and body["csrfToken"]


@pytest.mark.django_db
def test_activate_token_cannot_be_reused():
    _invited_customer()
    client = APIClient()
    client.post("/api/activate/", {"token": TOKEN, "password": STRONG_PASSWORD}, format="json")

    response = APIClient().post(
        "/api/activate/", {"token": TOKEN, "password": STRONG_PASSWORD}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("token", ["", "b" * 64])
def test_activate_rejects_missing_or_unknown_token(token):
    _invited_customer()

    response = APIClient().post(
        "/api/activate/", {"token": token, "password": STRONG_PASSWORD}, format="json"
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid or expired activation link"}
    assert not User.objects.exists()


@pytest.mark.django_db
def test_activate_rejects_an_expired_token():
    _invited_customer(expires_in_days=-1)

    response = APIClient().post(
        "/api/activate/", {"token": TOKEN, "password": STRONG_PASSWORD}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_activate_returns_409_when_an_account_already_uses_the_email():
    _invited_customer()
    create_user("U_TAKEN", email="guest@example.com")

    response = APIClient().post(
        "/api/activate/", {"token": TOKEN, "password": STRONG_PASSWORD}, format="json"
    )

    assert response.status_code == 409
    assert Customer.objects.get(pk="C_GUEST").user is None


@pytest.mark.django_db
def test_activate_rejects_a_weak_password():
    _invited_customer()

    response = APIClient().post(
        "/api/activate/", {"token": TOKEN, "password": "123"}, format="json"
    )

    assert response.status_code == 400
    assert not User.objects.exists()
    assert Customer.objects.get(pk="C_GUEST").activation_token_hash


@pytest.mark.django_db
def test_activate_is_rate_limited_by_ip(monkeypatch):
    monkeypatch.setattr(ActivateRateThrottle, "rate", "2/min", raising=False)
    client = APIClient()

    for _ in range(2):
        client.post("/api/activate/", {"token": "x", "password": "y"}, format="json")
    blocked = client.post("/api/activate/", {"token": "x", "password": "y"}, format="json")

    assert blocked.status_code == 429
