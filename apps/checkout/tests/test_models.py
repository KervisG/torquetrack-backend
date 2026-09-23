"""Tests de los modelos `Order` y `Payment` (tablas `orders` y `payments`).
`Payment.order` es FK a `Order`; `Order.customer` es FK a
`apps.customers.Customer`.
"""
from decimal import Decimal

import pytest

from apps.checkout.models import Order, Payment
from tests.factories import create_customer


def _insert_customer(customer_id):
    create_customer(customer_id, email=f"{customer_id}@example.com")


def _insert_order(order_id, number, customer_id, status, payment_status, data):
    Order.objects.create(
        id=order_id,
        number=number,
        customer_id=customer_id,
        status=status,
        payment_status=payment_status,
        data=data,
    )


def _insert_payment(payment_id, order_id, provider, status, amount, data):
    Payment.objects.create(
        id=payment_id,
        order_id=order_id,
        provider=provider,
        status=status,
        amount=amount,
        data=data,
    )


@pytest.mark.django_db
def test_reads_paid_order_linked_to_customer():
    _insert_customer("cus_order_1")
    _insert_order(
        "ord_1", "O-2001", "cus_order_1", "PAID", "PAID",
        {"lineItems": [{"productId": "gm-65-injection-pump-dorman-502550", "qty": 1}]},
    )

    order = Order.objects.select_related("customer").get(pk="ord_1")

    assert order.status == "PAID"
    assert order.payment_status == "PAID"
    assert order.customer.pk == "cus_order_1"


@pytest.mark.django_db
def test_reads_open_unpaid_order_without_customer():
    _insert_order("ord_2", "O-2002", None, "OPEN", "UNPAID", {"lineItems": []})

    order = Order.objects.get(pk="ord_2")

    assert order.status == "OPEN"
    assert order.payment_status == "UNPAID"
    assert order.customer_id is None


@pytest.mark.django_db
def test_reads_stripe_payment_linked_to_order_with_decimal_amount():
    _insert_order("ord_3", "O-2003", None, "PAID", "PAID", {"lineItems": []})
    _insert_payment(
        "pay_1", "ord_3", "stripe", "succeeded", "149.97",
        {"stripePaymentIntentId": "pi_123"},
    )

    payment = Payment.objects.select_related("order").get(pk="pay_1")

    assert payment.provider == "stripe"
    assert payment.amount == Decimal("149.97")
    assert payment.order.pk == "ord_3"
    assert payment.data["stripePaymentIntentId"] == "pi_123"
