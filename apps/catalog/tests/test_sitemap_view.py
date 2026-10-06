"""`GET /api/sitemap.xml`: sitemap público para buscadores, sin sesión ni
proveedores que mockear.

Lista las páginas fijas del SPA (inicio = catálogo, cotización y políticas) y
cada producto ACTIVO como `{APP_URL}/product/<slug>` con su `lastmod` (fecha
de `updated_at`). Las URLs apuntan al SPA (`APP_URL`), no al host del backend:
Nginx sirve este mismo documento en `/sitemap.xml`.
"""
from datetime import UTC, datetime
from xml.etree import ElementTree

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Product

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _entries(response) -> dict:
    root = ElementTree.fromstring(response.content)
    return {
        url.findtext("sm:loc", namespaces=NS): url.findtext("sm:lastmod", namespaces=NS)
        for url in root.findall("sm:url", NS)
    }


@pytest.fixture(autouse=True)
def _app_url(settings):
    settings.APP_URL = "https://shop.example.com/"


@pytest.mark.django_db
def test_sitemap_is_public_xml():
    response = APIClient().get("/api/sitemap.xml")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/xml")
    assert response.content.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')


@pytest.mark.django_db
def test_sitemap_lists_the_static_storefront_pages():
    entries = _entries(APIClient().get("/api/sitemap.xml"))

    for path in (
        "/",
        "/quote",
        "/policies",
        "/policies/shipping",
        "/policies/returns",
        "/policies/privacy",
        "/policies/terms",
    ):
        assert f"https://shop.example.com{path}" in entries


@pytest.mark.django_db
def test_sitemap_lists_active_products_by_slug_with_lastmod():
    Product.objects.create(
        id="p1",
        data={"title": "Bosch CP3 Injection Pump", "partNumber": "0445020150"},
        updated_at=datetime(2026, 9, 30, 23, 0, tzinfo=UTC),
    )
    Product.objects.create(id="p2", data={"title": "Retired Pump"}, active=False)

    entries = _entries(APIClient().get("/api/sitemap.xml"))

    assert entries["https://shop.example.com/product/bosch-cp3-injection-pump-0445020150"] == (
        "2026-09-30"
    )
    assert not any("retired-pump" in loc for loc in entries)
