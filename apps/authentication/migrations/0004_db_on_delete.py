# Django 5.2 crea las FK como NO ACTION y aplica on_delete solo desde el ORM;
# esto lo lleva también a Postgres para que un DELETE hecho fuera del ORM no
# falle ni deje filas huérfanas. Django 6.0 lo resuelve con `db_on_delete`.
# Un `AlterField` futuro sobre estas FK las recrea sin ON DELETE:
# `tests/test_db_on_delete.py` lo detecta.
#
# `users.role_id` queda NO ACTION a propósito: en el ORM es PROTECT.
# `django_admin_log.user_id` apunta a `users` porque `User` es el
# `AUTH_USER_MODEL`: por eso depende de `admin.0001_initial`, que crea esa tabla.
from django.db import migrations

CASCADE_FOREIGN_KEYS = [
    ("account_tokens", "account_tokens_user_id_e0356cbc_fk_users_id", "user_id", "users"),
    ("django_admin_log", "django_admin_log_user_id_c564eba6_fk_users_id", "user_id", "users"),
]


def _recreate(foreign_keys, on_delete):
    return ";".join(
        f"ALTER TABLE {table} DROP CONSTRAINT {name},"
        f" ADD CONSTRAINT {name} FOREIGN KEY ({column}) REFERENCES {target}(id)"
        f"{on_delete} DEFERRABLE INITIALLY DEFERRED"
        for table, name, column, target in foreign_keys
    )


class Migration(migrations.Migration):
    dependencies = [
        ("authentication", "0003_cache_table"),
        ("admin", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            _recreate(CASCADE_FOREIGN_KEYS, " ON DELETE CASCADE"),
            reverse_sql=_recreate(CASCADE_FOREIGN_KEYS, ""),
        ),
    ]
