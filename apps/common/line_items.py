"""Líneas y totales de pedidos y cotizaciones: una fila por línea y una
columna por total, no un array y un objeto dentro del JSON.

`LineItem` es la base abstracta de `OrderItem` y `QuoteItem`,
`DocumentTotals` la de las columnas de totales, y `LineItemsMixin` hace que
`data` del dueño siga siendo la forma de la API: `details` (el JSON) más
`items` armado desde las filas y `totals` desde las columnas. Las dos apps
comparten así una sola forma de línea y convertir una cotización en pedido
es copiar filas. Aquí no hay tablas: `common` no tiene modelos concretos.
"""
from django.db import models, transaction

from apps.common.numbers import ZERO, money_decimal


class LineItem(models.Model):
    position = models.PositiveSmallIntegerField()
    # Sin producto es una línea personalizada del panel, o uno ya borrado:
    # `title` y `part_number` son la foto del momento de la venta.
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    title = models.TextField(blank=True, default="")
    part_number = models.TextField(blank=True, default="")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    core_charge = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)

    class Meta:
        abstract = True
        ordering = ["position"]

    def as_dict(self) -> dict:
        line = {} if self.product_id is None else {"productId": self.product_id}
        return {
            **line,
            "title": self.title,
            "partNumber": self.part_number,
            "quantity": self.quantity,
            "unitPrice": float(self.unit_price),
            "coreCharge": float(self.core_charge),
        }


# Clave de `totals` en la API -> columna.
TOTAL_COLUMNS = {
    "subtotal": "subtotal",
    "core": "core_total",
    "shipping": "shipping_total",
    "tax": "tax_total",
    "discount": "discount_total",
    "total": "total",
}


class DocumentTotals(models.Model):
    """Totales de un pedido o cotización. `NULL` es "sin dato": un documento
    en armado aún no los tiene, y `discount` solo existe si lo hay."""

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    core_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    shipping_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        abstract = True


def total_constraints(table: str) -> list:
    """`total` queda sin CHECK: un descuento mayor que la suma lo deja negativo."""
    return [
        models.CheckConstraint(
            condition=models.Q(**{f"{column}__gte": 0}), name=f"{table}_{column}_non_negative"
        )
        for column in ("subtotal", "core_total", "shipping_total", "tax_total", "discount_total")
    ]


def line_item_constraints(table: str) -> list:
    """Los CHECK de cada tabla de líneas; el nombre lleva la tabla porque es
    único en todo el esquema."""
    return [
        models.CheckConstraint(condition=models.Q(quantity__gte=1), name=f"{table}_quantity"),
        models.CheckConstraint(
            condition=models.Q(unit_price__gte=0), name=f"{table}_unit_price_non_negative"
        ),
        models.CheckConstraint(
            condition=models.Q(core_charge__gte=0), name=f"{table}_core_charge_non_negative"
        ),
    ]


def _first(item: dict, *keys):
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


def normalize_line(item: dict) -> dict:
    """Lee la forma del panel (`quantity`/`unitPrice`/`productId`) y la vieja
    del storefront (`qty`/`price`/`id`). Quien guarda ya validó con
    `price_lines`; aquí solo se traduce."""
    product_id = _first(item, "productId", "id")
    quantity = _first(item, "quantity", "qty")
    return {
        "product_id": None if product_id in (None, "") else str(product_id),
        "title": str(item.get("title") or ""),
        "part_number": str(item.get("partNumber") or ""),
        "quantity": int(quantity) if quantity is not None else 1,
        "unit_price": money_decimal(_first(item, "unitPrice", "price") or 0),
        "core_charge": money_decimal(item.get("coreCharge") or 0),
    }


def _line_dict(line: dict) -> dict:
    """La forma de la API de una línea normalizada que aún no es fila."""
    head = {} if line["product_id"] is None else {"productId": line["product_id"]}
    return {
        **head,
        "title": line["title"],
        "partNumber": line["part_number"],
        "quantity": line["quantity"],
        "unitPrice": float(line["unit_price"]),
        "coreCharge": float(line["core_charge"]),
    }


class LineItemsMixin:
    """Para un modelo con `details` (JSON), las columnas de `DocumentTotals`
    y la relación inversa `items`.

    Asignar `data` con `items` reemplaza las líneas al guardar, y con `totals`
    reemplaza los totales; sin esas claves quedan como están.
    `save(update_fields=[..., "data"])` guarda `details` y los totales. Una
    lista conviene pedirla con `prefetch_related("items")`."""

    @property
    def data(self) -> dict:
        merged = dict(self.details or {})
        items = self.line_items()
        if items:
            merged["items"] = items
        totals = {
            key: float(getattr(self, column))
            for key, column in TOTAL_COLUMNS.items()
            if getattr(self, column) is not None
        }
        if totals:
            merged["totals"] = totals
        return merged

    @data.setter
    def data(self, value: dict) -> None:
        value = dict(value or {})
        if "items" in value:
            self._pending_items = [normalize_line(item) for item in value.pop("items") or []]
        if "totals" in value:
            totals = value.pop("totals")
            totals = totals if isinstance(totals, dict) else {}
            for key, column in TOTAL_COLUMNS.items():
                amount = totals.get(key)
                setattr(self, column, None if amount in (None, "") else money_decimal(amount))
        self.details = value

    def line_items(self) -> list[dict]:
        pending = self.__dict__.get("_pending_items")
        if pending is not None:
            return [_line_dict(line) for line in pending]
        if self._state.adding:
            return []
        return [item.as_dict() for item in self.items.all()]

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "data" in update_fields:
            kwargs["update_fields"] = [
                *(f for f in update_fields if f != "data"),
                "details",
                *TOTAL_COLUMNS.values(),
            ]
        with transaction.atomic():
            super().save(*args, **kwargs)
            pending = self.__dict__.pop("_pending_items", None)
            if pending is not None:
                self._replace_line_items(pending)

    def _replace_line_items(self, lines: list[dict]) -> None:
        relation = self._meta.get_field("items")
        item_model = relation.related_model
        product_model = item_model._meta.get_field("product").related_model
        # Un id que no está en el catálogo (borrado o inventado) queda como
        # línea personalizada: la FK no admite un producto inexistente.
        wanted = {line["product_id"] for line in lines if line["product_id"]}
        existing = set(product_model.objects.filter(pk__in=wanted).values_list("pk", flat=True))
        self.items.all().delete()
        item_model.objects.bulk_create(
            item_model(
                **{
                    **line,
                    "product_id": line["product_id"] if line["product_id"] in existing else None,
                    "position": position,
                    relation.field.name: self,
                }
            )
            for position, line in enumerate(lines)
        )
        getattr(self, "_prefetched_objects_cache", {}).pop("items", None)
