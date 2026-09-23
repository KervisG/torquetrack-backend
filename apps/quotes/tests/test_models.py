"""Tests del modelo `Quote` (tabla `quotes`), incluida la FK `customer` a
`apps.customers.Customer`. Los tokens del enlace público viven en `data`.
"""

import pytest

from apps.quotes.models import Quote
from tests.factories import create_customer


def _insert_customer(customer_id):
    create_customer(customer_id, email=f"{customer_id}@example.com")


def _insert_quote(quote_id, number, customer_id, status, data):
    Quote.objects.create(
        id=quote_id, number=number, customer_id=customer_id, status=status, data=data
    )


@pytest.mark.django_db
def test_reads_quote_linked_to_existing_customer():
    _insert_customer("cus_quote_1")
    _insert_quote(
        "quo_1", "Q-1001", "cus_quote_1", "BUILDING",
        {"lineItems": [{"productId": "gm-65-injection-pump-dorman-502550", "qty": 1}]},
    )

    quote = Quote.objects.select_related("customer").get(pk="quo_1")

    assert quote.number == "Q-1001"
    assert quote.customer.pk == "cus_quote_1"
    assert quote.data["lineItems"][0]["qty"] == 1


@pytest.mark.django_db
def test_reads_sent_quote_with_expiry():
    from django.utils import timezone

    expires_at = timezone.now()
    Quote.objects.create(
        id="quo_2", number="Q-1002", status="SENT", data={"lineItems": []}, expires_at=expires_at
    )

    quote = Quote.objects.get(pk="quo_2")

    assert quote.status == "SENT"
    assert quote.customer_id is None
    assert quote.expires_at is not None
