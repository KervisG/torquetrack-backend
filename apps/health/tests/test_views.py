"""`GET /api/health/`: chequeo de salud para el hosting y el balanceador.

Público (sin sesión, sin CSRF, sin throttle) y sin datos: solo dice si la base
responde. El 503 se prueba de dos formas: parcheando `database_is_available`
en `apps.health.views` (donde se usa) y reemplazando la `connection` de
`apps.health.services.database` por un doble que lanza `OperationalError`,
así nunca se toca la conexión real de los tests. Sin proveedores.
"""
import pytest
from django.db import OperationalError
from rest_framework.test import APIClient

from apps.health.services import database
from tests.factories import create_user, session_client

HEALTH_URL = "/api/health/"


class _DownConnection:
    def ensure_connection(self):
        raise OperationalError("could not connect to server")

    def is_usable(self):
        return False


class _UnusableConnection:
    def ensure_connection(self):
        return None

    def is_usable(self):
        return False


@pytest.mark.django_db
def test_health_is_ok_when_the_database_answers():
    response = APIClient().get(HEALTH_URL)

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.django_db
def test_health_is_503_when_the_database_is_down(monkeypatch):
    monkeypatch.setattr("apps.health.views.database_is_available", lambda: False)

    response = APIClient().get(HEALTH_URL)

    assert response.status_code == 503
    assert response.json() == {"ok": False, "error": "Database unavailable"}


def test_database_is_unavailable_when_the_connection_fails(monkeypatch):
    monkeypatch.setattr(database, "connection", _DownConnection())

    assert database.database_is_available() is False


def test_database_is_unavailable_when_a_kept_connection_is_broken(monkeypatch):
    # Con `CONN_MAX_AGE` la conexión sobrevive entre requests:
    # `ensure_connection` no hace nada si ya existe, así que se pregunta también
    # si sigue usable.
    monkeypatch.setattr(database, "connection", _UnusableConnection())

    assert database.database_is_available() is False


@pytest.mark.django_db
def test_database_is_available_with_the_test_database():
    assert database.database_is_available() is True


@pytest.mark.django_db
def test_health_does_not_need_a_session_and_ignores_one():
    create_user("U_HEALTH")
    client, _ = session_client("U_HEALTH", enforce_csrf=True)

    assert client.get(HEALTH_URL).status_code == 200


@pytest.mark.django_db
def test_health_is_never_throttled():
    client = APIClient()

    statuses = {client.get(HEALTH_URL).status_code for _ in range(30)}

    assert statuses == {200}


@pytest.mark.django_db
def test_health_only_answers_get():
    response = APIClient().post(HEALTH_URL, {}, format="json")

    assert response.status_code == 405
    assert "error" in response.json()
