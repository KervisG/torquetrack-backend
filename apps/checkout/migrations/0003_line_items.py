# Las líneas del pedido pasan de `data["items"]` a `order_items`, una fila
# por línea con columnas tipadas. El JSON, renombrado a `details`, guarda el
# resto. Las líneas viejas del storefront (`qty`/`price`/`id`) y las de una
# cotización (`quantity`/`unitPrice`/`productId`) quedan con la misma forma.
from decimal import Decimal, InvalidOperation

import django.db.models.deletion
from django.db import migrations, models


def _first(item, *keys):
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


def _amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")
    if not amount.is_finite() or amount < 0:
        return Decimal("0.00")
    return amount.quantize(Decimal("0.01"))


def _quantity(value):
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        return 1
    return quantity if quantity >= 1 else 1


def move_items(apps, schema_editor):
    """Copia congelada de `normalize_line` de `apps/common/line_items.py`."""
    Order = apps.get_model("checkout", "Order")
    OrderItem = apps.get_model("checkout", "OrderItem")
    Product = apps.get_model("catalog", "Product")
    product_ids = set(Product.objects.values_list("pk", flat=True))
    for order in Order.objects.all():
        details = dict(order.details or {})
        items = details.pop("items", None)
        rows = []
        for position, item in enumerate(items if isinstance(items, list) else []):
            if not isinstance(item, dict):
                continue
            product_id = _first(item, "productId", "id")
            rows.append(
                OrderItem(
                    order=order,
                    position=position,
                    product_id=str(product_id) if str(product_id) in product_ids else None,
                    title=str(item.get("title") or ""),
                    part_number=str(item.get("partNumber") or ""),
                    quantity=_quantity(_first(item, "quantity", "qty")),
                    unit_price=_amount(_first(item, "unitPrice", "price") or 0),
                    core_charge=_amount(item.get("coreCharge") or 0),
                )
            )
        OrderItem.objects.bulk_create(rows)
        order.details = details
        order.save(update_fields=["details"])


def restore_items(apps, schema_editor):
    Order = apps.get_model("checkout", "Order")
    for order in Order.objects.prefetch_related("items"):
        lines = [
            {
                **({"productId": item.product_id} if item.product_id else {}),
                "title": item.title,
                "partNumber": item.part_number,
                "quantity": item.quantity,
                "unitPrice": float(item.unit_price),
                "coreCharge": float(item.core_charge),
            }
            for item in order.items.order_by("position")
        ]
        if lines:
            order.details = {**(order.details or {}), "items": lines}
            order.save(update_fields=["details"])


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0003_product_columns"),
        ("checkout", "0002_db_on_delete"),
    ]

    operations = [
        migrations.RenameField(model_name="order", old_name="data", new_name="details"),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("position", models.PositiveSmallIntegerField()),
                ("title", models.TextField(blank=True, default="")),
                ("part_number", models.TextField(blank=True, default="")),
                ("quantity", models.PositiveIntegerField()),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=12)),
                (
                    "core_charge",
                    models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="checkout.order",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="catalog.product",
                    ),
                ),
            ],
            options={
                "db_table": "order_items",
                "ordering": ["position"],
                "abstract": False,
                "constraints": [
                    models.UniqueConstraint(
                        fields=("order", "position"), name="order_items_position"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gte", 1)), name="order_items_quantity"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("unit_price__gte", 0)),
                        name="order_items_unit_price_non_negative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("core_charge__gte", 0)),
                        name="order_items_core_charge_non_negative",
                    ),
                ],
            },
        ),
        migrations.RunPython(move_items, restore_items),
    ]
