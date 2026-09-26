# Django 5.2 crea las FK como NO ACTION y aplica SET_NULL solo desde el ORM;
# esto lo lleva también a Postgres para que un DELETE hecho fuera del ORM no
# falle ni deje filas huérfanas. Django 6.0 lo resuelve con `db_on_delete`.
# Un `AlterField` futuro sobre estas FK las recrea sin ON DELETE:
# `tests/test_db_on_delete.py` lo detecta.
from django.db import migrations

FOREIGN_KEYS = [
    ("orders", "orders_customer_id_b7016332_fk_customers_id", "customer_id", "customers"),
    ("payments", "payments_order_id_6086ad70_fk_orders_id", "order_id", "orders"),
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
        ("checkout", "0004_move_document_sequence"),
    ]

    operations = [
        migrations.RunSQL(_recreate(" ON DELETE SET NULL"), reverse_sql=_recreate("")),
    ]
