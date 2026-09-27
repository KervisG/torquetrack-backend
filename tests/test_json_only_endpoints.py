"""Los endpoints públicos que mutan sin exigir CSRF (login, alta, activación,
enlaces por correo, y checkout, cotización y carrito como invitado) aceptan
solo JSON.

Un formulario HTML de otro sitio puede mandar `x-www-form-urlencoded` o
`multipart` sin preflight de CORS, pero no `application/json`: aceptar solo
JSON cierra el login CSRF y los envíos cross-site a estas rutas. Ningún
proveedor se llama: el 415 corta antes del service.
"""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from tests.factories import create_user
from tests.fakes import forbid_resend

JSON_ONLY_PATHS = [
    "/api/login/",
    "/api/register/",
    "/api/activate/",
    "/api/verify-email/",
    "/api/password-reset/",
    "/api/password-reset/confirm/",
    "/api/checkout/",
    "/api/quote/request/",
    "/api/cart/sync/",
]
FORM_BODY = {"email": "pat@example.com", "password": "Diesel-Torque-2026!", "token": "x"}


@pytest.fixture(autouse=True)
def _clear_throttle_history(db):
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _no_providers(settings, monkeypatch):
    # Con key configurada el checkout pasa el chequeo de Stripe y llega a leer
    # el body; `forbid_resend` prueba que ningún correo sale.
    settings.STRIPE_SECRET_KEY = "sk_test_fake_not_real"
    forbid_resend(monkeypatch)


@pytest.mark.django_db
@pytest.mark.parametrize("path", JSON_ONLY_PATHS)
@pytest.mark.parametrize("format_name", ["multipart", None])
def test_form_encoded_post_is_rejected_with_415(path, format_name):
    create_user("U_PAT", email="pat@example.com")
    client = APIClient()
    if format_name == "multipart":
        response = client.post(path, FORM_BODY, format="multipart")
    else:
        response = client.post(
            path,
            "email=pat%40example.com&password=Diesel-Torque-2026%21&token=x",
            content_type="application/x-www-form-urlencoded",
        )

    assert response.status_code == 415
    assert "Unsupported media type" in response.json()["detail"]


@pytest.mark.django_db
def test_json_login_still_works():
    create_user("U_PAT", email="pat@example.com", password="Diesel-Torque-2026!")

    response = APIClient().post(
        "/api/login/",
        {"email": "pat@example.com", "password": "Diesel-Torque-2026!"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
