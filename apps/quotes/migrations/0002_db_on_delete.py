# Django 5.2 crea las FK como NO ACTION y aplica on_delete solo desde el ORM;
# esto lo lleva también a Postgres para que un DELETE hecho fuera del ORM no
# falle ni deje filas huérfanas. Django 6.0 lo resuelve con `db_on_delete`.
# Un `AlterField` futuro sobre estas FK las recrea sin ON DELETE:
# `tests/test_db_on_delete.py` lo detecta.
from django.db import migrations

SET_NULL_FOREIGN_KEYS = [
    ("quotes", "quotes_customer_id_61dcfeac_fk_customers_id", "customer_id", "customers"),
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
        ("quotes", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            _recreate(SET_NULL_FOREIGN_KEYS, " ON DELETE SET NULL"),
            reverse_sql=_recreate(SET_NULL_FOREIGN_KEYS, ""),
        ),
    ]
