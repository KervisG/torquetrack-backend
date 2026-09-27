"""El esquema OpenAPI cubre las APIView que spectacular no puede adivinar.

Se genera igual que `manage.py spectacular`, sin request y sin proveedores.
"""
import pytest
from drf_spectacular.drainage import GENERATOR_STATS, reset_generator_stats
from drf_spectacular.generators import SchemaGenerator


@pytest.fixture(scope="module")
def schema():
    reset_generator_stats()
    generated = SchemaGenerator().get_schema(request=None, public=True)
    return generated


def test_schema_has_no_unguessed_serializers(schema):
    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    unguessed = [message for message in messages if "unable to guess serializer" in message]
    collisions = [
        message
        for message in messages
        if "Status6b4Enum" in message or "multiple names for the same choice set" in message
    ]
    assert unguessed == []
    assert collisions == []


def test_schema_enum_names_are_stable(schema):
    names = set(schema.get("components", {}).get("schemas", {}))
    assert "Status6b4Enum" not in names
    assert "products_retrieve" not in {
        operation.get("operationId")
        for path in schema["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict)
    }
