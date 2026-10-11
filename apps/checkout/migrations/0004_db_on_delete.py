# Lleva a Postgres el ON DELETE de las líneas: CASCADE con su pedido y
# SET NULL con el producto, así la línea queda como foto de la venta. Ver
# `catalog/0002_db_on_delete`.
from django.db import migrations

CASCADE_FOREIGN_KEYS = [
    ("order_items", "order_items_order_id_412ad78b_fk_orders_id", "order_id", "orders"),
]
SET_NULL_FOREIGN_KEYS = [
    ("order_items", "order_items_product_id_dd557d5a_fk_products_id", "product_id", "products"),
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
        ("checkout", "0003_line_items"),
    ]

    operations = [
        migrations.RunSQL(
            _recreate(CASCADE_FOREIGN_KEYS, " ON DELETE CASCADE"),
            reverse_sql=_recreate(CASCADE_FOREIGN_KEYS, ""),
        ),
        migrations.RunSQL(
            _recreate(SET_NULL_FOREIGN_KEYS, " ON DELETE SET NULL"),
            reverse_sql=_recreate(SET_NULL_FOREIGN_KEYS, ""),
        ),
    ]
