"""Documentación OpenAPI del catálogo: `GET /api/products/<id o slug>/` y
`GET /api/sitemap.xml`.

El esquema se genera con `SchemaGenerator` sin request; no hay proveedores que
mockear. Lo que se assertea sale de `apps/catalog/docs/`.
"""
import pytest
from drf_spectacular.drainage import GENERATOR_STATS, reset_generator_stats
from drf_spectacular.generators import SchemaGenerator


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def test_catalog_views_generate_without_errors_or_warnings():
    reset_generator_stats()
    with GENERATOR_STATS.silence():
        SchemaGenerator().get_schema(request=None, public=True)

    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    reset_generator_stats()
    assert [m for m in messages if "Sitemap" in m or "ProductPublic" in m] == []


def test_product_detail_documents_lookup_by_id_or_slug(schema):
    op = schema["paths"]["/api/products/{id}/"]["get"]

    assert "slug" in op["description"]
    record = schema["components"]["schemas"]["CatalogRecord"]
    assert "slug" in record["properties"]


def test_sitemap_is_documented_as_xml(schema):
    op = schema["paths"]["/api/sitemap.xml"]["get"]

    assert op["operationId"] == "catalog_sitemap"
    assert "application/xml" in op["responses"]["200"]["content"]
