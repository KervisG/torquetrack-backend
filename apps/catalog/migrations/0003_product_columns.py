# Los campos de negocio de `products.data` pasan a columnas tipadas y el JSON,
# renombrado a `attributes`, se queda con los datos descriptivos. El índice
# GIN sobre el JSON se va: ninguna consulta filtra por su contenido.
#
# Un valor que no entra en su columna (texto donde va un número, monto
# negativo, años invertidos) se queda en `attributes` en lugar de perderse o
# de frenar la migración.
from decimal import Decimal, InvalidOperation

from django.db import migrations, models

# Copia congelada de `COLUMN_FIELDS` de `apps/catalog/models/product.py`: una
# migración no importa código de la app.
COLUMN_FIELDS = {
    "title": ("title", "text"),
    "partNumber": ("part_number", "text"),
    "price": ("price", "money"),
    "compareAt": ("compare_at", "money"),
    "coreCharge": ("core_charge", "money"),
    "purchaseCost": ("purchase_cost", "money"),
    "stock": ("stock", "text"),
    "make": ("make", "text"),
    "model": ("model", "text"),
    "category": ("category", "text"),
    "yearFrom": ("year_from", "year"),
    "yearTo": ("year_to", "year"),
}


def _convert(kind, value):
    """El valor de la columna, o `None` si no entra (y queda en el JSON)."""
    if kind == "text":
        return str(value)
    if isinstance(value, bool):
        return None
    if kind == "year":
        try:
            year = int(value)
        except (TypeError, ValueError):
            return None
        return year if year >= 0 else None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0:
        return None
    return number.quantize(Decimal("0.01"))


def move_to_columns(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    for product in Product.objects.all():
        attributes = dict(product.attributes or {})
        columns = {}
        for key, (column, kind) in COLUMN_FIELDS.items():
            value = attributes.get(key)
            if value is None or value == "":
                attributes.pop(key, None)
                continue
            converted = _convert(kind, value)
            if converted is not None:
                columns[column] = converted
                attributes.pop(key)
        year_from, year_to = columns.get("year_from"), columns.get("year_to")
        if year_from is not None and year_to is not None and year_to < year_from:
            attributes["yearFrom"] = columns.pop("year_from")
            attributes["yearTo"] = columns.pop("year_to")
        for column, value in columns.items():
            setattr(product, column, value)
        product.attributes = attributes
        product.save(update_fields=[*columns, "attributes"])


def move_to_json(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    for product in Product.objects.all():
        attributes = dict(product.attributes or {})
        for key, (column, kind) in COLUMN_FIELDS.items():
            value = getattr(product, column)
            if value is not None:
                attributes[key] = float(value) if kind == "money" else value
        product.attributes = attributes
        product.save(update_fields=["attributes"])


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_db_on_delete"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="product",
            name="idx_products_data",
        ),
        migrations.RenameField(
            model_name="product",
            old_name="data",
            new_name="attributes",
        ),
        migrations.AddField(
            model_name="product",
            name="category",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="compare_at",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="core_charge",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="make",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="model",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="part_number",
            field=models.TextField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="price",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="purchase_cost",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="stock",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="title",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="year_from",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="product",
            name="year_to",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        # Antes de los CHECK: así validan los valores ya movidos.
        migrations.RunPython(move_to_columns, move_to_json),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(
                condition=models.Q(("price__gte", 0)), name="products_price_non_negative"
            ),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(
                condition=models.Q(("compare_at__gte", 0)), name="products_compare_at_non_negative"
            ),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(
                condition=models.Q(("core_charge__gte", 0)),
                name="products_core_charge_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(
                condition=models.Q(("purchase_cost__gte", 0)),
                name="products_purchase_cost_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(
                condition=models.Q(("year_to__gte", models.F("year_from"))),
                name="products_year_range",
            ),
        ),
    ]
