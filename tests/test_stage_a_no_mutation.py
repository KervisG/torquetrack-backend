"""Proves the core Stage A safety guarantee (design decision #3): Django's
own `migrate` never creates, alters, or drops the tables `scripts/schema.sql`
already defines for the live Next.js app.

Two independent proofs:
1. `test_migrate_created_none_of_the_stage_a_tables` — a REAL before/after
   comparison: `stage_a_tables_before_schema_sql` (from `conftest.py`)
   snapshots the table list right after Django's own `migrate` ran, before
   `scripts/schema.sql` executes. None of the Stage A tables may appear yet.
2. `test_sqlmigrate_emits_no_sql_for_stage_a_migrations` — inspects the
   migration plan output directly: since every Stage A `0001_initial`
   migration wraps its `CreateModel` in `SeparateDatabaseAndState` with an
   empty `database_operations` list, `sqlmigrate` must print no SQL at all.
"""
from io import StringIO

import pytest
from django.core.management import call_command

from tests.stage_a_tables import STAGE_A_TABLES

STAGE_A_APPS = ["accounts", "customers", "catalog", "cart", "checkout", "quotes"]


@pytest.mark.django_db
def test_migrate_created_none_of_the_stage_a_tables(stage_a_tables_before_schema_sql):
    assert STAGE_A_TABLES.isdisjoint(stage_a_tables_before_schema_sql)


@pytest.mark.django_db
@pytest.mark.parametrize("app_label", STAGE_A_APPS)
def test_sqlmigrate_emits_no_sql_for_stage_a_migrations(app_label):
    """`sqlmigrate` always prints the `BEGIN`/`COMMIT` transaction wrapper
    and a comment header, even for a migration with zero real database
    operations — asserting `printed_sql == ""` would never pass for ANY
    migration, managed or not. The real proof of "zero DDL" is the absence
    of schema-mutating statements, which `SeparateDatabaseAndState` with an
    empty `database_operations` list guarantees.
    """
    out = StringIO()
    call_command("sqlmigrate", app_label, "0001", stdout=out)
    printed_sql = out.getvalue().strip().upper()

    forbidden_ddl = ("CREATE TABLE", "ALTER TABLE", "DROP TABLE", "CREATE INDEX")
    found = [kw for kw in forbidden_ddl if kw in printed_sql]
    assert not found, (
        f"expected zero DDL for {app_label}.0001_initial (managed=False via "
        f"SeparateDatabaseAndState), found {found} in:\n{printed_sql}"
    )
