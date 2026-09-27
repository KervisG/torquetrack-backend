# Lleva el CASCADE del ORM a Postgres; ver `checkout/0005_db_on_delete`.
# `users.role_id` queda NO ACTION a propósito: en el ORM es PROTECT.
#
# `django_admin_log.user_id` apunta a `users` porque `User` es el
# `AUTH_USER_MODEL`; en el ORM es CASCADE y aquí se lleva también a Postgres.
# Por eso depende de `admin.0001_initial`, que crea esa tabla.
from django.db import migrations

FOREIGN_KEYS = [
    ("account_tokens", "account_tokens_user_id_e0356cbc_fk_users_id", "user_id", "users"),
    ("django_admin_log", "django_admin_log_user_id_c564eba6_fk_users_id", "user_id", "users"),
]


def _recreate(on_delete):
    return ";".join(
        f"ALTER TABLE {table} DROP CONSTRAINT {name},"
        f" ADD CONSTRAINT {name} FOREIGN KEY ({column}) REFERENCES {target}(id)"
        f"{on_delete} DEFERRABLE INITIALLY DEFERRED"
        for table, name, column, target in FOREIGN_KEYS
    )


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0002_cache_table"),
        ("admin", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(_recreate(" ON DELETE CASCADE"), reverse_sql=_recreate("")),
    ]
