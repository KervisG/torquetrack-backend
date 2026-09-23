"""El ORM de Django es dueño de todas las tablas del backend.

La base de test se arma solo con `migrate` (no hay `schema.sql`). Estos
tests prueban que no queda ningún modelo `managed = False`, que `migrate`
crea cada tabla de dominio y que el estado de las migraciones coincide con
los modelos (`makemigrations --check`).
"""
from io import StringIO

import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import connection

DOMAIN_TABLES = {
    "users",
    "roles",
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

# Tablas del Next.js abandonado que ya no tienen dueño en el backend.
RETIRED_LEGACY_TABLES = {"sessions", "employee_roles"}


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
def test_migrate_leaves_no_retired_legacy_table():
    assert RETIRED_LEGACY_TABLES.isdisjoint(_public_tables())


@pytest.mark.django_db
def test_models_have_no_pending_migrations():
    out = StringIO()

    call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
