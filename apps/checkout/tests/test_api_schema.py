"""Documentación OpenAPI de `POST /api/admin/orders/{order_id}/refunds/`.

El esquema se genera con `SchemaGenerator` sin request, igual que
`manage.py spectacular`; no hay proveedores que mockear. Lo que se assertea
sale de `apps/checkout/docs/`: si alguien borra la extensión o deja de
registrarla en `CheckoutConfig.ready()`, estos tests fallan. Solo cubre la
ruta de reembolsos; las demás views de checkout todavía no están
documentadas y sus errores de esquema son previos.
"""
import pytest
from drf_spectacular.drainage import GENERATOR_STATS, reset_generator_stats
from drf_spectacular.generators import SchemaGenerator

REFUNDS_PATH = "/api/admin/orders/{order_id}/refunds/"


def _examples(operation, status):
    content = operation["responses"][status]["content"]["application/json"]
    return [example["value"] for example in content.get("examples", {}).values()]


def _component(schema, node):
    return schema["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]]


@pytest.fixture(scope="module")
def operation():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    return schema, schema["paths"][REFUNDS_PATH]["post"]


def test_refunds_route_documents_summary_tag_and_body(operation):
    schema, op = operation

    assert op["summary"]
    assert "payments.refund" in op["description"]
    assert op["tags"] == ["admin: orders"]
    body = _component(schema, op["requestBody"]["content"]["application/json"]["schema"])
    assert set(body["properties"]) == {"amount", "reason"}
    assert body.get("required", []) == []


def test_refunds_route_documents_every_response_with_its_literal_errors(operation):
    schema, op = operation

    created = _component(schema, op["responses"]["201"]["content"]["application/json"]["schema"])
    assert {"id", "paymentId", "amount", "status", "reason", "createdBy", "createdAt"} <= set(
        created["properties"]
    )
    assert {
        "error": "Refund amount must be a positive number with at most two decimals"
    } in _examples(op, "400")
    assert {"error": "Order not found"} in _examples(op, "404")
    assert {"error": "Only paid orders can be refunded"} in _examples(op, "409")
    assert {"error": "Stripe request failed; see server logs."} in _examples(op, "502")
    assert "403" in op["responses"]


def test_schema_generation_emits_no_warnings_or_errors_for_the_refunds_view():
    reset_generator_stats()
    with GENERATOR_STATS.silence():
        SchemaGenerator().get_schema(request=None, public=True)

    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    reset_generator_stats()
    assert [message for message in messages if "AdminOrderRefundsView" in message] == []
