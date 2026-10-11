"""Totales del pedido y de la cotización en columnas `Decimal`:
`data["totals"]` conserva la forma de la API y la base puede sumarlos."""
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import Sum

from apps.checkout.models import Order
from apps.quotes.models import Quote

TOTALS = {"subtotal": 379.98, "core": 50.0, "shipping": 18.5, "tax": 27.1, "total": 475.58}


def _order(order_id="OID1", number="1001", **data):
    return Order.objects.create(id=order_id, number=number, data=data)


@pytest.mark.django_db
def test_totals_are_stored_in_decimal_columns():
    _order(totals=TOTALS, cartId="cart_1")

    order = Order.objects.get(pk="OID1")

    assert (order.subtotal, order.core_total) == (Decimal("379.98"), Decimal("50.00"))
    assert (order.shipping_total, order.tax_total) == (Decimal("18.50"), Decimal("27.10"))
    assert (order.discount_total, order.total) == (None, Decimal("475.58"))
    assert order.details == {"cartId": "cart_1"}


@pytest.mark.django_db
def test_data_rebuilds_the_totals_with_the_api_shape():
    _order(totals={**TOTALS, "discount": 10.0, "total": 465.58})

    assert Order.objects.get(pk="OID1").data["totals"] == {
        **TOTALS,
        "discount": 10.0,
        "total": 465.58,
    }


@pytest.mark.django_db
def test_an_order_without_totals_has_no_totals_key():
    _order(cartId="cart_1")

    assert Order.objects.get(pk="OID1").data == {"cartId": "cart_1"}


@pytest.mark.django_db
def test_reassigning_data_without_totals_keeps_them():
    _order(totals=TOTALS)
    order = Order.objects.get(pk="OID1")

    order.data = {**order.details, "cancelReason": "expired"}
    order.save(update_fields=["data"])

    assert Order.objects.get(pk="OID1").data["totals"] == TOTALS


@pytest.mark.django_db
def test_reassigning_data_with_totals_replaces_them():
    _order(totals={**TOTALS, "discount": 10.0})
    order = Order.objects.get(pk="OID1")

    order.data = {**order.data, "totals": {"subtotal": 5, "total": 5}}
    order.save(update_fields=["data"])

    assert Order.objects.get(pk="OID1").data["totals"] == {"subtotal": 5.0, "total": 5.0}


@pytest.mark.django_db
def test_the_database_can_add_up_the_totals():
    _order("OID1", "1001", totals=TOTALS)
    _order("OID2", "1002", totals=TOTALS)

    assert Order.objects.aggregate(sum=Sum("total"))["sum"] == Decimal("951.16")


@pytest.mark.django_db
@pytest.mark.parametrize("key", ["subtotal", "core", "shipping", "tax", "discount"])
def test_the_database_rejects_a_negative_amount(key):
    with pytest.raises(IntegrityError), transaction.atomic():
        _order(totals={key: -1})


@pytest.mark.django_db
def test_quote_totals_use_the_same_columns():
    Quote.objects.create(id="QID1", number="Q1", data={"totals": TOTALS})

    quote = Quote.objects.get(pk="QID1")

    assert quote.total == Decimal("475.58")
    assert quote.data == {"totals": TOTALS}
