"""Documentación OpenAPI de las rutas de `apps.authentication` (`/api/login/`,
`/api/logout/`, `/api/session/`, `/api/password-reset/`,
`/api/password-reset/confirm/` y `/api/verify-email/resend/`). Las del panel
de usuarios y roles se prueban en `apps/authorization/tests/test_api_schema.py`.

El esquema se genera con `SchemaGenerator` sin request, igual que
`manage.py spectacular`; no hay proveedores que mockear. Las views son
`APIView` sin serializer, así que todo lo que se assertea aquí sale de las
`OpenApiViewExtension` de `apps/authentication/docs/`: si alguien las borra o deja de
registrarlas en `AuthenticationConfig.ready()`, estos tests fallan.

El test de advertencias vacía `GENERATOR_STATS` antes de generar y filtra los
mensajes que nombran a `apps.authentication` (sus views, su autenticación o sus rutas):
las advertencias de otras apps no son de este módulo.
"""
import re

import pytest
from drf_spectacular.drainage import GENERATOR_STATS, reset_generator_stats
from drf_spectacular.generators import SchemaGenerator

from tests.factories import create_staff_user, session_client

# Ruta -> métodos documentados. Son todas las rutas de `apps/authentication/urls.py`.
AUTH_OPERATIONS = {
    "/api/login/": ["post"],
    "/api/logout/": ["post"],
    "/api/session/": ["get"],
    "/api/password-reset/": ["post"],
    "/api/password-reset/confirm/": ["post"],
    "/api/verify-email/resend/": ["post"],
}
# Operaciones que leen un body JSON. `logout/` y `verify-email/resend/`
# ignoran el body, así que no lo documentan.
OPERATIONS_WITH_BODY = {
    ("/api/login/", "post"),
    ("/api/password-reset/", "post"),
    ("/api/password-reset/confirm/", "post"),
}
AUTH_MESSAGE = re.compile(
    r"apps[\\/.]authentication|"
    + "|".join(re.escape(path) for path in AUTH_OPERATIONS)
)


def _auth_operations(schema):
    for path, methods in AUTH_OPERATIONS.items():
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


def test_every_auth_route_is_in_the_schema(schema):
    for path, methods in AUTH_OPERATIONS.items():
        assert path in schema["paths"], path
        for method in methods:
            assert method in schema["paths"][path], (path, method)


def test_every_auth_operation_has_summary_description_and_tag(schema):
    for path, method, operation in _auth_operations(schema):
        assert operation.get("summary"), (path, method)
        assert operation.get("description"), (path, method)
        assert operation["tags"] == ["auth"], (path, method)


def test_every_auth_operation_documents_a_2xx_response_with_schema(schema):
    for path, method, operation in _auth_operations(schema):
        successes = [code for code in operation["responses"] if code.startswith("2")]
        assert successes, (path, method)
        for code in successes:
            content = operation["responses"][code]["content"]["application/json"]
            assert content["schema"], (path, method, code)


def test_body_operations_document_the_request_and_the_rest_do_not(schema):
    for path, method, operation in _auth_operations(schema):
        if (path, method) in OPERATIONS_WITH_BODY:
            assert "application/json" in operation["requestBody"]["content"], (path, method)
        else:
            assert "requestBody" not in operation, (path, method)


def test_login_documents_required_credentials_and_its_responses(schema):
    operation = schema["paths"]["/api/login/"]["post"]

    body = _request_schema(schema, operation)
    assert set(body["required"]) == {"email", "password"}
    assert body["properties"]["email"]["type"] == "string"
    assert body["properties"]["password"]["type"] == "string"
    assert {"200", "400", "401", "429"} <= set(operation["responses"])
    assert {"error": "Incorrect email or password"} in _example_values(operation, "401")


def test_password_reset_confirm_documents_the_literal_errors(schema):
    operation = schema["paths"]["/api/password-reset/confirm/"]["post"]

    body = _request_schema(schema, operation)
    assert set(body["required"]) == {"token", "password"}
    errors = _example_values(operation, "400")
    assert {"error": "Invalid or expired reset link"} in errors
    assert {"error": "Password required"} in errors
    assert "429" in operation["responses"]


@pytest.mark.django_db
def test_served_schema_includes_the_auth_documentation():
    create_staff_user("usr_auth_schema")
    client, _ = session_client("usr_auth_schema")

    response = client.get("/api/schema/", {"format": "json"})

    assert response.status_code == 200
    login = response.json()["paths"]["/api/login/"]["post"]
    assert login["tags"] == ["auth"]
    assert "requestBody" in login


def test_schema_generation_emits_no_warnings_or_errors_for_auth():
    reset_generator_stats()
    with GENERATOR_STATS.silence():
        SchemaGenerator().get_schema(request=None, public=True)

    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    auth_messages = [message for message in messages if AUTH_MESSAGE.search(message)]
    reset_generator_stats()
    assert auth_messages == []
