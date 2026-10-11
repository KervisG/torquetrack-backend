# Lleva a Postgres el CASCADE de las fotos con su producto. Ver
# `catalog/0002_db_on_delete`.
from django.db import migrations

FOREIGN_KEYS = [
    (
        "product_images",
        "product_images_product_id_28ebf5f0_fk_products_id",
        "product_id",
        "products",
    ),
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
        ("catalog", "0004_product_images"),
    ]

    operations = [
        migrations.RunSQL(_recreate(" ON DELETE CASCADE"), reverse_sql=_recreate("")),
    ]
