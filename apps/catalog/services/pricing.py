"""Precio de las líneas y totales: la única normalización que usan el checkout,
la solicitud de cotización, el panel de cotizaciones, su presentación y las
líneas de Stripe.

Vive en `catalog` porque el catálogo es dueño del precio y está por debajo de
`checkout` y `quotes`. `build_totals` también vive aquí y no en
`apps/common/numbers.py`: la forma `subtotal`/`core`/`shipping`/`tax`/`total`
(el core charge de las piezas diesel) es del dominio, y `common` solo tiene
helpers sin dominio.

Todo el dinero es `Decimal` redondeado con `money_decimal`; el `float` aparece
solo al serializar (`serialize_totals` y los `money(...)` de cada caller).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from apps.common.numbers import ZERO, money, money_decimal

MAX_STOREFRONT_QUANTITY = 99
STOREFRONT_QUANTITY_ERROR = (
    f"Item quantity must be a whole number from 1 to {MAX_STOREFRONT_QUANTITY}"
)


class PricingError(Exception):
    """Base de los rechazos; cada caller la traduce a su respuesta."""


class InvalidQuantity(PricingError):
    """Una línea sin cantidad entera dentro del rango, o que no es un objeto."""


class InvalidPrice(PricingError):
    """Un precio propio (solo panel) negativo o que no es un número."""


class UnpricedProducts(PricingError):
    """Productos del catálogo sin precio positivo: un error de carga que no se
    vende gratis. `lines` permite nombrarlos en el mensaje."""

    def __init__(self, lines: list[PricedLine]):
        super().__init__("Catalog products without a valid price")
        self.lines = lines


@dataclass(frozen=True)
class PricedLine:
    item: dict
    product: dict | None
    quantity: int
    unit_price: Decimal
    core_charge: Decimal

    @property
    def product_id(self):
        if self.product is not None:
            return self.product.get("id")
        return self.item.get("productId") or self.item.get("id")

    @property
    def line_total(self) -> Decimal:
        return money_decimal(self.unit_price * self.quantity)

    @property
    def core_total(self) -> Decimal:
        return money_decimal(self.core_charge * self.quantity)


@dataclass(frozen=True)
class PricedLines:
    lines: list[PricedLine]
    subtotal: Decimal
    core: Decimal


def _raw_quantity(item: dict):
    value = item.get("quantity")
    return item.get("qty") if value is None else value


def parse_quantity(value, *, max_quantity: int | None = MAX_STOREFRONT_QUANTITY) -> int | None:
    """Entero >= 1 (y <= `max_quantity`), `1` si no viene, o `None` si es
    inválido: una fracción, un cero o un negativo cobraría algo que no se
    despacha. `bool` es un `int` en Python y no es una cantidad."""
    if value is None:
        return 1
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        quantity = value
    elif isinstance(value, float) and value.is_integer():
        quantity = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        quantity = int(value.strip())
    else:
        return None
    if quantity < 1 or (max_quantity is not None and quantity > max_quantity):
        return None
    return quantity


def _custom_amount(value) -> Decimal:
    """Monto que tipeó el staff: ausente es 0; negativo o no numérico es error."""
    if value is None:
        return ZERO
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        raise InvalidPrice("Custom price is not a number")
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise InvalidPrice("Custom price is not a number") from exc
    if not amount.is_finite() or amount < 0:
        raise InvalidPrice("Custom price must be 0 or more")
    return money_decimal(value)


def _catalog_products(raw_items: list[dict]) -> dict[str, dict]:
    from apps.catalog.models import Product

    ids = [str(item.get("productId") or item.get("id")) for item in raw_items]
    return {
        product.id: (product.data or {})
        for product in Product.objects.filter(id__in=ids, active=True)
    }


def price_lines(
    raw_items: list,
    *,
    allow_custom_price: bool = False,
    max_quantity: int | None = MAX_STOREFRONT_QUANTITY,
) -> PricedLines:
    """Reprecia las líneas y suma subtotal y core.

    Sin `allow_custom_price` (storefront) el precio sale del catálogo, se
    ignora el del cliente, los productos inexistentes o inactivos se descartan
    y un precio no positivo lanza `UnpricedProducts`. Con `allow_custom_price`
    (panel) el precio es el de la línea (`unitPrice`, o el `price` heredado),
    puede ser 0 y no se lee el catálogo. `max_quantity=None` quita solo el
    tope superior de la cantidad.
    """
    if any(not isinstance(item, dict) for item in raw_items):
        raise InvalidQuantity("Each line must be an object")
    quantities = [
        parse_quantity(_raw_quantity(item), max_quantity=max_quantity) for item in raw_items
    ]
    if any(quantity is None for quantity in quantities):
        raise InvalidQuantity("Line quantity out of range")

    products = {} if allow_custom_price else _catalog_products(raw_items)
    lines = []
    for item, quantity in zip(raw_items, quantities, strict=True):
        if allow_custom_price:
            raw_price = item.get("unitPrice")
            if raw_price is None:
                raw_price = item.get("price")
            lines.append(
                PricedLine(
                    item=item,
                    product=None,
                    quantity=quantity,
                    unit_price=_custom_amount(raw_price),
                    core_charge=_custom_amount(item.get("coreCharge")),
                )
            )
            continue
        product = products.get(str(item.get("productId") or item.get("id")))
        if not product:
            continue
        lines.append(
            PricedLine(
                item=item,
                product=product,
                quantity=quantity,
                unit_price=money_decimal(product.get("price")),
                core_charge=money_decimal(product.get("coreCharge")),
            )
        )

    unpriced = [line for line in lines if line.product is not None and line.unit_price <= 0]
    if unpriced:
        raise UnpricedProducts(unpriced)
    return PricedLines(
        lines=lines,
        subtotal=sum((line.line_total for line in lines), ZERO),
        core=sum((line.core_total for line in lines), ZERO),
    )


def build_totals(subtotal, core, shipping=0, tax=0, discount=0) -> dict[str, Decimal]:
    """Único cálculo de totales: cada monto y el total redondeados con
    `money_decimal`. `discount` solo aparece si no es cero, así los totales
    guardados conservan sus cinco claves."""
    amounts = {
        "subtotal": money_decimal(subtotal),
        "core": money_decimal(core),
        "shipping": money_decimal(shipping),
        "tax": money_decimal(tax),
    }
    discount = money_decimal(discount)
    total = sum(amounts.values(), ZERO) - discount
    if discount:
        amounts["discount"] = discount
    return {**amounts, "total": money_decimal(total)}


def serialize_totals(totals: dict) -> dict[str, float]:
    """Totales para el JSON (`Order.data`, `Quote.data` y las respuestas)."""
    return {key: money(value) for key, value in totals.items()}
