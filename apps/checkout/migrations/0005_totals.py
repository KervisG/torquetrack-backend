# Los totales pasan de `orders.details["totals"]` a columnas `Decimal`, que la
# base puede sumar y validar. Si algún monto no entra en su columna (no es un
# número, o es negativo donde no puede serlo), los totales de ese documento se
# quedan en el JSON en lugar de perderse o de frenar la migración.
from decimal import Decimal, InvalidOperation

from django.db import migrations, models

# Copia congelada de `TOTAL_COLUMNS` de `apps/common/line_items.py`.
TOTAL_COLUMNS = {
    "subtotal": "subtotal",
    "core": "core_total",
    "shipping": "shipping_total",
    "tax": "tax_total",
    "discount": "discount_total",
    "total": "total",
}


def _amounts(totals):
    """Los montos por columna, o `None` si alguno no entra."""
    amounts = {}
    for key, column in TOTAL_COLUMNS.items():
        value = totals.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return None
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            return None
        if not amount.is_finite() or (amount < 0 and key != "total"):
            return None
        amounts[column] = amount.quantize(Decimal("0.01"))
    return amounts


def move_totals(apps, schema_editor):
    Model = apps.get_model("checkout", "Order")
    for document in Model.objects.all():
        details = dict(document.details or {})
        totals = details.get("totals")
        amounts = _amounts(totals) if isinstance(totals, dict) else None
        if amounts is None:
            continue
        details.pop("totals")
        for column, amount in amounts.items():
            setattr(document, column, amount)
        document.details = details
        document.save(update_fields=[*amounts, "details"])


def restore_totals(apps, schema_editor):
    Model = apps.get_model("checkout", "Order")
    for document in Model.objects.all():
        totals = {
            key: float(getattr(document, column))
            for key, column in TOTAL_COLUMNS.items()
            if getattr(document, column) is not None
        }
        if totals:
            document.details = {**(document.details or {}), "totals": totals}
            document.save(update_fields=["details"])


class Migration(migrations.Migration):
    dependencies = [
        ("checkout", "0004_db_on_delete"),
        ("customers", "0003_profile_columns"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="core_total",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="discount_total",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="shipping_total",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="subtotal",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="tax_total",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="total",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        # Antes de los CHECK: así validan los valores ya movidos.
        migrations.RunPython(move_totals, restore_totals),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=models.Q(("subtotal__gte", 0)), name="orders_subtotal_non_negative"
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=models.Q(("core_total__gte", 0)), name="orders_core_total_non_negative"
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=models.Q(("shipping_total__gte", 0)),
                name="orders_shipping_total_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=models.Q(("tax_total__gte", 0)), name="orders_tax_total_non_negative"
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=models.Q(("discount_total__gte", 0)),
                name="orders_discount_total_non_negative",
            ),
        ),
    ]
