# Lleva el CASCADE del ORM a Postgres; ver `checkout/0005_db_on_delete`.
# `users.role_id` queda NO ACTION a propósito: en el ORM es PROTECT.
from django.db import migrations

FOREIGN_KEYS = [
    ("account_tokens", "account_tokens_user_id_e0356cbc_fk_users_id", "user_id", "users"),
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
        ("tt_auth", "0012_activation_tokens"),
    ]

    operations = [
        migrations.RunSQL(_recreate(" ON DELETE CASCADE"), reverse_sql=_recreate("")),
    ]
