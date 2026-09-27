"""Documentación OpenAPI de `GET`/`PUT /api/cart/` y `GET /api/admin/carts/`.

El esquema se genera con `SchemaGenerator` sin request, igual que
`manage.py spectacular`; no hay proveedores que mockear. Lo que se assertea
sale de `apps/cart/docs/`: si alguien borra una extensión o deja de
registrarla en `CartConfig.ready()`, estos tests fallan, y ninguna view de
`apps/cart` puede dejar errores ni avisos en el generador.
"""
import pytest
from drf_spectacular.drainage import GENERATOR_STATS, reset_generator_stats
from drf_spectacular.generators import SchemaGenerator

CART_PATH = "/api/cart/"
ADMIN_CARTS_PATH = "/api/admin/carts/"


def _component(schema, node):
    return schema["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]]


def _examples(operation, status):
    content = operation["responses"][status]["content"]["application/json"]
    return [example["value"] for example in content.get("examples", {}).values()]


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def test_cart_views_generate_without_errors_or_warnings():
    reset_generator_stats()
    with GENERATOR_STATS.silence():
        SchemaGenerator().get_schema(request=None, public=True)

    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    reset_generator_stats()
    assert [m for m in messages if "CartView" in m or "AdminCartsView" in m] == []


def test_get_cart_documents_the_repriced_lines(schema):
    op = schema["paths"][CART_PATH]["get"]

    assert op["summary"]
    assert op["tags"] == ["cart"]
    body = _component(schema, op["responses"]["200"]["content"]["application/json"]["schema"])
    assert set(body["properties"]) == {"items", "subtotal", "core", "notices"}
    line = _component(schema, body["properties"]["items"]["items"])
    assert set(line["properties"]) == {
        "id",
        "qty",
        "title",
        "partNumber",
        "price",
        "coreCharge",
        "lineTotal",
        "priceChanged",
        "previousPrice",
    }


def test_put_cart_documents_its_body_and_literal_errors(schema):
    op = schema["paths"][CART_PATH]["put"]

    request = _component(schema, op["requestBody"]["content"]["application/json"]["schema"])
    assert set(request["properties"]) == {"items", "acknowledgePrices"}
    item = _component(schema, request["properties"]["items"]["items"])
    assert set(item["properties"]) == {"id", "qty"}
    errors = {example["error"] for example in _examples(op, "400")}
    assert "Item quantity must be a whole number from 1 to 99" in errors
    assert "Each product can appear only once in the cart" in errors
    assert {"403", "415"} <= set(op["responses"])


def test_admin_carts_documents_its_permission_and_rows(schema):
    op = schema["paths"][ADMIN_CARTS_PATH]["get"]

    assert "carts.view" in op["description"]
    rows = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert rows["type"] == "array"
    row = _component(schema, rows["items"])
    assert {"id", "status", "stage", "updatedAt", "items", "email"} <= set(row["properties"])
