"""La base de test se arma solo con `migrate`, sin ningún SQL externo."""
from importlib import import_module
from io import StringIO

import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import connection

DOMAIN_TABLES = {
    "users",
    "roles",
    "account_tokens",
    "customers",
    "products",
    "applications",
    "carts",
    "quotes",
    "orders",
    "payments",
    "activity_logs",
    "document_sequences",
}

RETIRED_TABLES = {"sessions", "employee_roles"}


def _public_tables():
    with connection.cursor() as cursor:
        return set(connection.introspection.table_names(cursor))


def test_every_model_is_managed_by_django():
    unmanaged = [
        model._meta.label for model in apps.get_models() if not model._meta.managed
    ]

    assert unmanaged == []


@pytest.mark.django_db
def test_migrate_creates_every_domain_table():
    assert DOMAIN_TABLES <= _public_tables()


@pytest.mark.django_db
def test_cache_table_migration_creates_the_database_cache_table():
    # El test runner ya corre `createcachetable` al crear la base de test, así
    # que se borra la tabla y se vuelve a correr la migración para probar que
    # `migrate` sola la crea en un deploy.
    migration = import_module("apps.authentication.migrations.0002_cache_table")
    with connection.schema_editor() as schema_editor:
        schema_editor.execute("DROP TABLE IF EXISTS django_cache")
        assert "django_cache" not in _public_tables()

        migration.create_cache_tables(None, schema_editor)

    assert "django_cache" in _public_tables()


@pytest.mark.django_db
def test_migrate_leaves_no_retired_table():
    assert RETIRED_TABLES.isdisjoint(_public_tables())


@pytest.mark.django_db
def test_models_have_no_pending_migrations():
    out = StringIO()

    call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
