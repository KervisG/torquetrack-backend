"""Documentación OpenAPI de `GET /api/admin/dashboard/` y
`GET /api/admin/dashboard/analytics/`.

El esquema se genera con `SchemaGenerator` sin request; no hay proveedores que
mockear. Lo que se assertea sale de `apps/dashboard/docs/`.
"""
import pytest
from drf_spectacular.drainage import GENERATOR_STATS, reset_generator_stats
from drf_spectacular.generators import SchemaGenerator

ANALYTICS_PATH = "/api/admin/dashboard/analytics/"


def _component(schema, node):
    return schema["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]]


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def test_dashboard_views_generate_without_errors_or_warnings():
    reset_generator_stats()
    with GENERATOR_STATS.silence():
        SchemaGenerator().get_schema(request=None, public=True)

    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    reset_generator_stats()
    assert [m for m in messages if "AdminDashboard" in m] == []


def test_analytics_documents_its_range_permission_and_body(schema):
    op = schema["paths"][ANALYTICS_PATH]["get"]

    assert op["operationId"] == "admin_dashboard_analytics"
    assert "dashboard.view" in op["description"]
    param = next(p for p in op["parameters"] if p["name"] == "range")
    assert set(param["schema"]["enum"]) == {"7d", "30d", "90d", "12m"}
    assert {"200", "400", "403"} <= set(op["responses"])
    body = _component(schema, op["responses"]["200"]["content"]["application/json"]["schema"])
    assert {
        "range",
        "granularity",
        "revenueSeries",
        "kpis",
        "ordersByStatus",
        "topProducts",
        "quoteFunnel",
        "cartFunnel",
    } <= set(body["properties"])
