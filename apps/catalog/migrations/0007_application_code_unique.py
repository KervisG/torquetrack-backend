# Con todas las filas completadas por `0006_product_fitment`, `code` pasa a ser
# obligatorio y único, y las FK de `product_fitments` reciben su ON DELETE.
from django.db import migrations, models

# Django 5.2 crea las FK como NO ACTION y aplica CASCADE solo desde el ORM
# (ver `checkout/0005_db_on_delete`); `tests/test_db_on_delete.py` lo fija.
FOREIGN_KEYS = [
    (
        "product_fitments_application_id_527f60cd_fk_applications_id",
        "application_id",
        "applications",
    ),
    ("product_fitments_product_id_e65a4de4_fk_products_id", "product_id", "products"),
]


def _recreate(on_delete):
    return ";".join(
        f"ALTER TABLE product_fitments DROP CONSTRAINT {name},"
        f" ADD CONSTRAINT {name} FOREIGN KEY ({column}) REFERENCES {target}(id)"
        f"{on_delete} DEFERRABLE INITIALLY DEFERRED"
        for name, column, target in FOREIGN_KEYS
    )


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0006_product_fitment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="application",
            name="code",
            field=models.CharField(max_length=120, unique=True),
        ),
        migrations.RunSQL(_recreate(" ON DELETE CASCADE"), reverse_sql=_recreate("")),
    ]
