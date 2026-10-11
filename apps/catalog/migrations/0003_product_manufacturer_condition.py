# El fabricante y la condición del producto pasan de `attributes` a columnas:
# la búsqueda de la tienda filtra por ellos y arma con ellos sus opciones.
from django.db import migrations, models

COLUMNS = ("manufacturer", "condition")


def move_to_columns(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    for product in Product.objects.all():
        attributes = dict(product.attributes or {})
        for column in COLUMNS:
            value = attributes.pop(column, None)
            setattr(product, column, None if value in (None, "") else str(value))
        product.attributes = attributes
        product.save(update_fields=[*COLUMNS, "attributes"])


def move_to_json(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    for product in Product.objects.all():
        values = {
            column: getattr(product, column)
            for column in COLUMNS
            if getattr(product, column) is not None
        }
        product.attributes = {**(product.attributes or {}), **values}
        product.save(update_fields=["attributes"])


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_db_on_delete"),
    ]

    operations = [
        *(
            migrations.AddField(
                model_name="product", name=column, field=models.TextField(blank=True, null=True)
            )
            for column in COLUMNS
        ),
        migrations.RunPython(move_to_columns, move_to_json),
    ]
