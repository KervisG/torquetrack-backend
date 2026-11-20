"""Pasa el historial de las apps viejas `authentication` y `authorization` a
`accounts` y `roles`. Las tablas tienen `db_table` fijo, así que solo cambian
las filas de `django_migrations` y `django_content_type`. Corre antes de
`migrate`: una base vieja fallaría con `InconsistentMigrationHistory`. Es
idempotente y no hace nada en una base nueva."""
from django.core.management.base import BaseCommand
from django.db import connection, transaction

RENAMED_MIGRATIONS = {
    ("authentication", "0001_initial"): ("accounts", "0001_initial"),
    ("authentication", "0002_initial"): ("accounts", "0002_user_role"),
    ("authentication", "0003_cache_table"): ("accounts", "0003_cache_table"),
    ("authentication", "0004_db_on_delete"): ("accounts", "0004_db_on_delete"),
    ("authorization", "0001_initial"): ("roles", "0001_initial"),
    ("authorization", "0002_seed_roles"): ("roles", "0002_seed_roles"),
}
RENAMED_LABELS = {"authentication": "accounts", "authorization": "roles"}


class Command(BaseCommand):
    help = "Renames the authentication/authorization history to accounts/roles."

    def handle(self, *args, **options):
        tables = set(connection.introspection.table_names())
        renamed = 0
        with transaction.atomic(), connection.cursor() as cursor:
            if "django_migrations" in tables:
                for (old_app, old_name), (new_app, new_name) in RENAMED_MIGRATIONS.items():
                    cursor.execute(
                        "UPDATE django_migrations SET app = %s, name = %s "
                        "WHERE app = %s AND name = %s",
                        [new_app, new_name, old_app, old_name],
                    )
                    renamed += cursor.rowcount
            if "django_content_type" in tables:
                for old_label, new_label in RENAMED_LABELS.items():
                    cursor.execute(
                        "UPDATE django_content_type SET app_label = %s WHERE app_label = %s",
                        [new_label, old_label],
                    )
        self.stdout.write(f"Renamed {renamed} migration(s).")
