# Lleva el SET_NULL del ORM a Postgres; ver `checkout/0005_db_on_delete`.
from django.db import migrations

FOREIGN_KEYS = [
    ("customers", "customers_user_id_28f6c6eb_fk_users_id", "user_id", "users"),
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
        ("customers", "0004_drop_activation_columns"),
    ]

    operations = [
        migrations.RunSQL(_recreate(" ON DELETE SET NULL"), reverse_sql=_recreate("")),
    ]
