"""`price_lines` y `build_totals` de `apps/catalog/services/pricing.py`: la única
normalización de líneas y el único cálculo de totales que usan el checkout, la
solicitud de cotización y el panel. Sin proveedores; los productos se crean con
el ORM.

Se assertea a propósito que el precio del cliente se ignora fuera del panel,
que la cantidad es un entero de 1 a 99 en el storefront y que el dinero sale en
`Decimal` redondeado a centavos antes de multiplicar.
"""

from decimal import Decimal

import pytest

from apps.catalog.models import Product
from apps.catalog.services.pricing import (
    MAX_STOREFRONT_QUANTITY,
    InvalidPrice,
    InvalidQuantity,
    UnpricedProducts,
    build_totals,
    price_lines,
    serialize_totals,
)

PRODUCT_ID = "ford-73-injector"


def _insert_product(product_id=PRODUCT_ID, active=True, **data):
    fields = {"id": product_id, "title": "Injector", "partNumber": "AP63992", **data}
    Product.objects.create(id=product_id, data=fields, active=active)


@pytest.mark.django_db
def test_catalog_price_wins_over_the_price_the_client_sent():
    _insert_product(price=189.99, coreCharge=50)

    priced = price_lines([{"id": PRODUCT_ID, "qty": 2, "price": 0.01, "unitPrice": 0.01}])

    line = priced.lines[0]
    assert line.unit_price == Decimal("189.99")
    assert line.core_charge == Decimal("50.00")
    assert line.line_total == Decimal("379.98")
    assert priced.subtotal == Decimal("379.98")
    assert priced.core == Decimal("100.00")


@pytest.mark.django_db
def test_unit_price_is_rounded_to_cents_before_multiplying():
    # 3 × 19.995 con float da 59.985 → 59.99; la línea cobra 3 × 20.00.
    _insert_product(price=19.995, coreCharge=1.005)

    priced = price_lines([{"productId": PRODUCT_ID, "quantity": 3}])

    assert priced.subtotal == Decimal("60.00")
    assert priced.core == Decimal("3.03")


@pytest.mark.django_db
def test_unknown_and_inactive_products_are_dropped():
    _insert_product(price=10)
    _insert_product("retired", active=False, price=10)

    priced = price_lines([{"id": PRODUCT_ID}, {"id": "retired"}, {"id": "ghost"}])

    assert [line.product_id for line in priced.lines] == [PRODUCT_ID]
    assert priced.lines[0].quantity == 1


@pytest.mark.django_db
@pytest.mark.parametrize("quantity", [0, -1, 2.5, "abc", True, MAX_STOREFRONT_QUANTITY + 1, [2]])
def test_storefront_rejects_a_quantity_outside_one_to_ninety_nine(quantity):
    _insert_product(price=10)

    with pytest.raises(InvalidQuantity):
        price_lines([{"id": PRODUCT_ID, "qty": quantity}])


@pytest.mark.django_db
@pytest.mark.parametrize("quantity, expected", [(1, 1), ("7", 7), (3.0, 3), (99, 99)])
def test_storefront_accepts_whole_quantities_in_range(quantity, expected):
    _insert_product(price=10)

    priced = price_lines([{"id": PRODUCT_ID, "qty": quantity}])

    assert priced.lines[0].quantity == expected


@pytest.mark.django_db
def test_a_line_that_is_not_an_object_is_an_invalid_quantity():
    with pytest.raises(InvalidQuantity):
        price_lines(["ford-73-injector"])


@pytest.mark.django_db
@pytest.mark.parametrize("price", [0, -5, None, "abc"])
def test_a_catalog_price_that_is_not_positive_is_rejected_with_the_lines(price):
    _insert_product(price=price)
    _insert_product("priced", price=10)

    with pytest.raises(UnpricedProducts) as excinfo:
        price_lines([{"id": PRODUCT_ID}, {"id": "priced"}])

    assert [line.product_id for line in excinfo.value.lines] == [PRODUCT_ID]


def test_custom_price_is_used_only_when_allowed_and_needs_no_catalog_row():
    priced = price_lines(
        [{"title": "Labor", "quantity": 3, "unitPrice": 19.995, "coreCharge": 1.005}],
        allow_custom_price=True,
        max_quantity=None,
    )

    line = priced.lines[0]
    assert line.product is None
    assert line.unit_price == Decimal("20.00")
    assert priced.subtotal == Decimal("60.00")
    assert priced.core == Decimal("3.03")


def test_custom_price_falls_back_to_the_legacy_price_key_and_allows_zero():
    priced = price_lines(
        [{"qty": 2, "price": 12.5}, {"quantity": 1, "unitPrice": 0}], allow_custom_price=True
    )

    assert [line.unit_price for line in priced.lines] == [Decimal("12.50"), Decimal("0.00")]
    assert priced.subtotal == Decimal("25.00")


@pytest.mark.parametrize(
    "field, value", [("unitPrice", -1), ("unitPrice", "abc"), ("coreCharge", -3)]
)
def test_custom_price_rejects_negative_or_non_numeric_amounts(field, value):
    with pytest.raises(InvalidPrice):
        price_lines([{"quantity": 1, "unitPrice": 10, field: value}], allow_custom_price=True)


def test_max_quantity_none_lifts_only_the_upper_bound():
    priced = price_lines(
        [{"quantity": 250, "unitPrice": 1}], allow_custom_price=True, max_quantity=None
    )
    assert priced.lines[0].quantity == 250

    with pytest.raises(InvalidQuantity):
        price_lines([{"quantity": 0, "unitPrice": 1}], allow_custom_price=True, max_quantity=None)


def test_build_totals_rounds_every_amount_and_the_total_in_decimal():
    totals = build_totals(Decimal("0.10"), 0.2, "5.005", 1.005)

    assert totals == {
        "subtotal": Decimal("0.10"),
        "core": Decimal("0.20"),
        "shipping": Decimal("5.01"),
        "tax": Decimal("1.01"),
        "total": Decimal("6.32"),
    }


def test_build_totals_subtracts_a_discount_and_reports_it():
    totals = build_totals(100, 0, 10, 5, discount=15)

    assert totals["discount"] == Decimal("15.00")
    assert totals["total"] == Decimal("100.00")


def test_serialize_totals_returns_json_numbers():
    assert serialize_totals(build_totals(Decimal("0.1"), Decimal("0.2"), 0, 0)) == {
        "subtotal": 0.1,
        "core": 0.2,
        "shipping": 0.0,
        "tax": 0.0,
        "total": 0.3,
    }
