"""Stage A binding tests for `quotes`, including the `customer_id` FK into
`apps.customers.Customer` (design decision #3). Magic-link tokens live
inside `data` jsonb for now (Stage B backfill types them later).
"""
import json

import pytest
from django.db import connection

from apps.quotes.models import Quote


def _insert_customer(customer_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into customers (id, email, data) values (%s, %s, %s)",
            [customer_id, f"{customer_id}@example.com", "{}"],
        )


def _insert_quote(quote_id, number, customer_id, status, data):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into quotes (id, number, customer_id, status, data)
            values (%s, %s, %s, %s, %s)
            """,
            [quote_id, number, customer_id, status, json.dumps(data)],
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
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into quotes (id, number, status, data, expires_at)
            values (%s, %s, %s, %s, %s)
            """,
            ["quo_2", "Q-1002", "SENT", json.dumps({"lineItems": []}), expires_at],
        )

    quote = Quote.objects.get(pk="quo_2")

    assert quote.status == "SENT"
    assert quote.customer_id is None
    assert quote.expires_at is not None
