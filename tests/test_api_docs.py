"""`GET /api/schema/`, `/api/docs/` (Swagger UI) y `/api/redoc/` (ReDoc).

La documentación describe también las rutas de `/api/admin/**`, así que solo
la ve el staff con sesión: un anónimo o un cliente reciben 403. Sin
proveedores que mockear.
"""
import pytest
from rest_framework.test import APIClient

from tests.factories import create_staff_user, create_user, session_client

DOC_URLS = ["/api/schema/", "/api/docs/", "/api/redoc/"]


@pytest.mark.django_db
@pytest.mark.parametrize("url", DOC_URLS)
def test_docs_are_hidden_from_anonymous_visitors(url):
    response = APIClient().get(url)

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("url", DOC_URLS)
def test_docs_are_hidden_from_customers(url):
    create_user("usr_docs_customer")
    client, _ = session_client("usr_docs_customer")

    response = client.get(url)

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/api/docs/", "/api/redoc/"])
def test_staff_sees_the_documentation_pages(url):
    create_staff_user("usr_docs_staff")
    client, _ = session_client("usr_docs_staff")

    response = client.get(url)

    assert response.status_code == 200
    assert "/api/schema/" in response.content.decode()


@pytest.mark.django_db
def test_schema_describes_storefront_and_admin_routes():
    create_staff_user("usr_docs_schema")
    client, _ = session_client("usr_docs_schema")

    response = client.get("/api/schema/", {"format": "json"})

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/checkout/" in paths
    assert "/api/admin/products/{product_id}/" in paths
    assert "/api/schema/" not in paths
