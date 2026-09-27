"""Documentación OpenAPI de las rutas de `apps.authorization` (`/api/admin/users/`,
`/api/admin/users/{user_id}/` y `/api/admin/roles/`).

El esquema se genera con `SchemaGenerator` sin request, igual que
`manage.py spectacular`; no hay proveedores que mockear. Las views son
`APIView` sin serializer, así que todo lo que se assertea aquí sale de las
`OpenApiViewExtension` de `apps/authorization/docs/`: si alguien las borra o
deja de registrarlas en `AuthorizationConfig.ready()`, estos tests fallan.
Reglas que se assertean a propósito: `/api/admin/users/` no documenta `POST`
(nadie crea cuentas desde el panel) y el `PUT` solo describe `role` y `active`.

El test de advertencias vacía `GENERATOR_STATS` antes de generar y filtra los
mensajes que nombran a `apps.authorization` (sus views o sus rutas): las advertencias
de otras apps no son de este módulo.
"""
import re

import pytest
from drf_spectacular.drainage import GENERATOR_STATS, reset_generator_stats
from drf_spectacular.generators import SchemaGenerator

# Ruta -> métodos documentados. Son todas las rutas de `apps/authorization/urls.py`.
AUTHORIZATION_OPERATIONS = {
    "/api/admin/roles/": ["get", "post"],
    "/api/admin/roles/{slug}/": ["put"],
    "/api/admin/users/": ["get"],
    "/api/admin/users/{user_id}/": ["put", "delete"],
}
# Operaciones que leen un body JSON.
OPERATIONS_WITH_BODY = {
    ("/api/admin/users/{user_id}/", "put"),
    ("/api/admin/roles/", "post"),
    ("/api/admin/roles/{slug}/", "put"),
}
AUTHORIZATION_MESSAGE = re.compile(
    r"apps[\\/.]authorization|"
    + "|".join(re.escape(path) for path in AUTHORIZATION_OPERATIONS)
)


def _authorization_operations(schema):
    for path, methods in AUTHORIZATION_OPERATIONS.items():
        for method in methods:
            yield path, method, schema["paths"][path][method]


def _request_schema(schema, operation):
    content = operation["requestBody"]["content"]["application/json"]["schema"]
    return _resolve(schema, content)


def _resolve(schema, node):
    ref = node.get("$ref")
    if ref is None:
        return node
    return schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]


def _example_values(operation, status):
    content = operation["responses"][status]["content"]["application/json"]
    return [example["value"] for example in content.get("examples", {}).values()]


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def test_every_authorization_route_is_in_the_schema(schema):
    for path, methods in AUTHORIZATION_OPERATIONS.items():
        assert path in schema["paths"], path
        for method in methods:
            assert method in schema["paths"][path], (path, method)


def test_every_authorization_operation_has_summary_description_and_tag(schema):
    for path, method, operation in _authorization_operations(schema):
        assert operation.get("summary"), (path, method)
        assert operation.get("description"), (path, method)
        assert operation["tags"] == ["admin: users"], (path, method)


def test_every_authorization_operation_documents_a_2xx_response_with_schema(schema):
    for path, method, operation in _authorization_operations(schema):
        successes = [code for code in operation["responses"] if code.startswith("2")]
        assert successes, (path, method)
        for code in successes:
            content = operation["responses"][code]["content"]["application/json"]
            assert content["schema"], (path, method, code)


def test_body_operations_document_the_request_and_the_rest_do_not(schema):
    for path, method, operation in _authorization_operations(schema):
        if (path, method) in OPERATIONS_WITH_BODY:
            assert "application/json" in operation["requestBody"]["content"], (path, method)
        else:
            assert "requestBody" not in operation, (path, method)


def test_admin_user_operations_document_401_and_403(schema):
    for path, method, operation in _authorization_operations(schema):
        assert "401" in operation["responses"], (path, method)
        assert "403" in operation["responses"], (path, method)
        assert {"error": "Unauthorized"} in _example_values(operation, "401")
        assert {"error": "Forbidden"} in _example_values(operation, "403")


def test_admin_users_has_no_create_operation(schema):
    assert set(schema["paths"]["/api/admin/users/"]) == {"get"}


def test_admin_user_update_documents_only_role_and_active(schema):
    operation = schema["paths"]["/api/admin/users/{user_id}/"]["put"]

    body = _request_schema(schema, operation)
    assert set(body["properties"]) == {"role", "active"}
    assert {"error": "Only role and active can be changed"} in _example_values(
        operation, "400"
    )
    assert {"error": "You cannot change your own role or active status"} in _example_values(
        operation, "403"
    )
    assert "409" not in operation["responses"]


def test_admin_user_update_and_delete_document_not_found(schema):
    detail = schema["paths"]["/api/admin/users/{user_id}/"]

    for method in ("put", "delete"):
        assert {"error": "User not found"} in _example_values(detail[method], "404")
    assert _request_schema(schema, detail["put"]).get("required", []) == []


def test_schema_generation_emits_no_warnings_or_errors_for_authorization():
    reset_generator_stats()
    with GENERATOR_STATS.silence():
        SchemaGenerator().get_schema(request=None, public=True)

    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    authorization_messages = [
        message for message in messages if AUTHORIZATION_MESSAGE.search(message)
    ]
    reset_generator_stats()
    assert authorization_messages == []
