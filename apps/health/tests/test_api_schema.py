"""Documentación OpenAPI de `GET /api/health/`.

El esquema se genera con `SchemaGenerator` sin request, igual que
`manage.py spectacular`. La view es un `APIView` sin serializer: lo que se
assertea sale de `apps/health/docs/extensions.py`. Sin proveedores.
"""
import re

import pytest
from drf_spectacular.drainage import GENERATOR_STATS, reset_generator_stats
from drf_spectacular.generators import SchemaGenerator

HEALTH_MESSAGE = re.compile(r"apps[\/.]health|HealthView|/api/health/")


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def test_health_is_documented_with_both_responses(schema):
    operation = schema["paths"]["/api/health/"]["get"]

    assert operation["operationId"] == "health_check"
    assert set(operation["responses"]) == {"200", "503"}


def test_health_schema_generation_has_no_warnings():
    reset_generator_stats()
    with GENERATOR_STATS.silence():
        SchemaGenerator().get_schema(request=None, public=True)

    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    health_messages = [message for message in messages if HEALTH_MESSAGE.search(message)]
    reset_generator_stats()
    assert health_messages == []
