# Lleva el SET_NULL del ORM a Postgres; ver `checkout/0005_db_on_delete`.
from django.db import migrations

FOREIGN_KEYS = [
    ("quotes", "quotes_customer_id_61dcfeac_fk_customers_id", "customer_id", "customers"),
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
        ("quotes", "0003_managed_quote"),
    ]

    operations = [
        migrations.RunSQL(_recreate(" ON DELETE SET NULL"), reverse_sql=_recreate("")),
    ]
