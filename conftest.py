"""Shared pytest-django fixtures for the Stage A migration-safety guarantee.

Stage A binds Django models to the Postgres tables that `scripts/schema.sql`
(repo root, shared with the frozen Next.js app) already defines. Those models
are `managed = False` and their `0001_initial` migrations use
`SeparateDatabaseAndState` with empty `database_operations`, so Django's own
`migrate` must never create, alter, or drop them.

This fixture overrides pytest-django's `django_db_setup` to:
1. Let the default fixture run first (creates the test DB and applies every
   Django migration exactly as `manage.py migrate` would).
2. Snapshot the table list that exists at that point, BEFORE any Stage A DDL
   runs — this is the "before" half of the no-mutation proof consumed by
   `backend/tests/test_stage_a_no_mutation.py`.
3. Only then apply the real `scripts/schema.sql` DDL directly (simulating
   what already provisions these tables in every real environment), so
   per-app model tests have real, production-shaped tables to read/write.
"""
from pathlib import Path

import pytest
from django.db import connection

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL_PATH = REPO_ROOT / "scripts" / "schema.sql"

_tables_before_schema_sql: set[str] = set()


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute(
                "select table_name from information_schema.tables"
                " where table_schema = 'public'"
            )
            _tables_before_schema_sql.update(row[0] for row in cursor.fetchall())

        schema_sql = SCHEMA_SQL_PATH.read_text()
        with connection.cursor() as cursor:
            cursor.execute(schema_sql)
    yield


@pytest.fixture(scope="session")
def stage_a_tables_before_schema_sql():
    """Table names that existed right after Django's own `migrate`, before
    `scripts/schema.sql` ran. Used to prove `migrate` created none of them.
    """
    return frozenset(_tables_before_schema_sql)
