"""Todo error de la API tiene una sola forma: `{"error": "<mensaje>"}`.

Los errores que arma DRF por su cuenta (sin sesión, sin permiso, 404, método
no permitido, media type, throttle, JSON mal formado, CSRF) pasan por
`config.exceptions.api_exception_handler`, que cambia `detail` por `error` sin
tocar el código de estado ni los headers (`Retry-After`, `Allow`,
`WWW-Authenticate`). Un error de validación con campos agrega `fields`.

Se prueba contra endpoints reales y contra views de prueba con
`APIRequestFactory` para los casos que ninguna view del proyecto dispara (401
de DRF, validación por campo). Sin proveedores: `forbid_resend` prueba que
ningún correo sale.
"""
import pytest
from django.core.cache import cache
from rest_framework import serializers
from rest_framework.authentication import BasicAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView

from apps.authentication.utils.throttling import LoginRateThrottle
from tests.factories import create_user, session_client
from tests.fakes import forbid_resend


@pytest.fixture(autouse=True)
def _clear_throttle_history(db):
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _no_emails(monkeypatch):
    forbid_resend(monkeypatch)


# --- endpoints reales -----------------------------------------------------------


@pytest.mark.django_db
def test_forbidden_admin_route_uses_error_key():
    response = APIClient().get("/api/admin/dashboard/")

    assert response.status_code == 403
    assert response.json() == {"error": "You do not have permission to perform this action."}


@pytest.mark.django_db
def test_unknown_catalog_product_uses_error_key():
    response = APIClient().get("/api/products/does-not-exist/")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]


@pytest.mark.django_db
def test_method_not_allowed_uses_error_key_and_keeps_allow_header():
    response = APIClient().get("/api/login/")

    assert response.status_code == 405
    assert response.json() == {"error": 'Method "GET" not allowed.'}
    assert "POST" in response["Allow"]


@pytest.mark.django_db
def test_unsupported_media_type_uses_error_key():
    response = APIClient().post(
        "/api/login/", "email=a%40example.com", content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 415
    assert response.json() == {
        "error": 'Unsupported media type "application/x-www-form-urlencoded" in request.'
    }


@pytest.mark.django_db
def test_malformed_json_uses_error_key():
    response = APIClient().post("/api/login/", "{", content_type="application/json")

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"].startswith("JSON parse error")


@pytest.mark.django_db
def test_throttled_request_uses_error_key_and_keeps_retry_after(monkeypatch):
    monkeypatch.setattr(LoginRateThrottle, "rate", "1/min", raising=False)
    client = APIClient()
    payload = {"email": "nobody@example.com", "password": "wrong"}
    client.post("/api/login/", payload, format="json")

    blocked = client.post("/api/login/", payload, format="json")

    assert blocked.status_code == 429
    assert set(blocked.json()) == {"error"}
    assert blocked.json()["error"].startswith("Request was throttled.")
    assert int(blocked["Retry-After"]) > 0


@pytest.mark.django_db
def test_csrf_failure_uses_error_key():
    create_user("U_CSRF_FORMAT")
    client, _ = session_client("U_CSRF_FORMAT", enforce_csrf=True)

    response = client.post("/api/logout/", {}, format="json")

    assert response.status_code == 403
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"].startswith("CSRF Failed:")


@pytest.mark.django_db
def test_application_errors_keep_their_shape():
    response = APIClient().post(
        "/api/login/", {"email": "nobody@example.com", "password": "wrong"}, format="json"
    )

    assert response.status_code == 401
    assert "error" in response.json()
    assert "detail" not in response.json()


# --- views de prueba -------------------------------------------------------------


class _BasicAuthView(APIView):
    # BasicAuthentication sí tiene `authenticate_header`, así que DRF responde
    # 401 (con la sesión de Django sería 403).
    authentication_classes = [BasicAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"ok": True})


class _PointSerializer(serializers.Serializer):
    email = serializers.EmailField()
    quantity = serializers.IntegerField(min_value=1)


class _FieldValidationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        _PointSerializer(data=request.data).is_valid(raise_exception=True)
        return Response({"ok": True})


class _PlainValidationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        raise ValidationError("Quantity is too large")


def test_drf_not_authenticated_uses_error_key_and_keeps_www_authenticate():
    request = APIRequestFactory().get("/probe/")

    response = _BasicAuthView.as_view()(request)

    assert response.status_code == 401
    assert response.data == {"error": "Authentication credentials were not provided."}
    assert response["WWW-Authenticate"].startswith("Basic")


def test_field_validation_errors_keep_the_fields_and_lead_with_the_first_message():
    request = APIRequestFactory().post(
        "/probe/", {"email": "not-an-email", "quantity": 0}, format="json"
    )

    response = _FieldValidationView.as_view()(request)

    assert response.status_code == 400
    assert response.data["error"] == "Enter a valid email address."
    assert response.data["fields"] == {
        "email": ["Enter a valid email address."],
        "quantity": ["Ensure this value is greater than or equal to 1."],
    }


def test_plain_validation_error_becomes_a_single_error():
    request = APIRequestFactory().post("/probe/", {}, format="json")

    response = _PlainValidationView.as_view()(request)

    assert response.status_code == 400
    assert response.data == {"error": "Quantity is too large"}
