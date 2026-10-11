"""Líneas del pedido en `order_items`: una fila por línea con columnas
tipadas. `Order.data["items"]` las devuelve siempre con la misma forma."""
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.catalog.models import Product
from apps.checkout.models import Order, OrderItem

LINE = {
    "productId": "gm-65-pump",
    "title": "Fuel Injection Pump",
    "partNumber": "502-550",
    "quantity": 2,
    "unitPrice": 189.99,
    "coreCharge": 150.0,
}


@pytest.fixture
def product(db):
    return Product.objects.create(id="gm-65-pump", data={"title": "Pump", "price": 189.99})


def _order(items, **data):
    return Order.objects.create(id="OID1", number="1001", data={"items": items, **data})


def test_each_line_is_a_typed_row(product):
    _order([LINE])

    (item,) = OrderItem.objects.filter(order_id="OID1")
    assert item.product == product
    assert (item.title, item.part_number) == ("Fuel Injection Pump", "502-550")
    assert item.quantity == 2
    assert (item.unit_price, item.core_charge) == (Decimal("189.99"), Decimal("150.00"))


def test_data_returns_the_lines_in_order_with_one_shape(product):
    second = {**LINE, "productId": None, "title": "Custom labor", "partNumber": ""}
    _order([LINE, second], cartId="cart_1")

    data = Order.objects.get(pk="OID1").data

    assert data["cartId"] == "cart_1"
    assert data["items"] == [
        LINE,
        {
            "title": "Custom labor",
            "partNumber": "",
            "quantity": 2,
            "unitPrice": 189.99,
            "coreCharge": 150.0,
        },
    ]


def test_details_keep_everything_but_the_lines(product):
    _order([LINE], cartId="cart_1")

    assert Order.objects.get(pk="OID1").details == {"cartId": "cart_1"}


def test_storefront_lines_with_qty_and_price_are_read_too(product):
    _order([{"id": "gm-65-pump", "title": "Pump", "partNumber": "P", "qty": 3, "price": 10}])

    (line,) = Order.objects.get(pk="OID1").data["items"]
    assert (line["productId"], line["quantity"], line["unitPrice"]) == ("gm-65-pump", 3, 10.0)


def test_a_product_that_does_not_exist_is_kept_as_a_custom_line(db):
    _order([{**LINE, "productId": "gone"}])

    (item,) = OrderItem.objects.filter(order_id="OID1")
    assert item.product is None
    assert item.title == "Fuel Injection Pump"


def test_reassigning_data_without_items_keeps_the_lines(product):
    _order([LINE])
    order = Order.objects.get(pk="OID1")

    order.data = {**order.details, "cancelReason": "expired"}
    order.save(update_fields=["data"])

    stored = Order.objects.get(pk="OID1")
    assert stored.details == {"cancelReason": "expired"}
    assert stored.data["items"] == [LINE]


def test_reassigning_data_with_items_replaces_the_lines(product):
    _order([LINE, LINE])
    order = Order.objects.get(pk="OID1")

    order.data = {**order.data, "items": [{**LINE, "quantity": 5}]}
    order.save(update_fields=["data"])

    assert [line["quantity"] for line in Order.objects.get(pk="OID1").data["items"]] == [5]


def test_deleting_the_order_deletes_its_lines(product):
    _order([LINE])

    Order.objects.filter(pk="OID1").delete()

    assert not OrderItem.objects.exists()


def test_deleting_the_product_keeps_the_line_without_it(product):
    _order([LINE])

    Product.objects.filter(pk="gm-65-pump").delete()

    (item,) = OrderItem.objects.filter(order_id="OID1")
    assert item.product is None
    assert item.title == "Fuel Injection Pump"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "column, value", [("quantity", 0), ("unit_price", -1), ("core_charge", -1)]
)
def test_the_database_rejects_invalid_lines(column, value):
    order = Order.objects.create(id="OID1", number="1001")
    row = {"order": order, "position": 0, "quantity": 1, "unit_price": 1, column: value}
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderItem.objects.create(**row)
