"""Stage A binding tests for the `carts` table (design decision #3).

Carts are upserted by client UUID and deleted on empty (spec: `cart/sync`) —
these tests only prove the Stage A read/write binding itself; the upsert
business rule is Phase 5's concern.
"""
import json

import pytest
from django.db import connection

from apps.cart.models import Cart


def _insert_cart(cart_id, items):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into carts (id, data) values (%s, %s)",
            [cart_id, json.dumps({"items": items})],
        )


@pytest.mark.django_db
def test_reads_cart_with_multiple_line_items():
    items = [
        {"productId": "gm-65-injection-pump-dorman-502550", "quantity": 2},
        {"productId": "ford-73-powerstroke-turbo", "quantity": 1},
    ]
    _insert_cart("cart_client_uuid_1", items)

    cart = Cart.objects.get(pk="cart_client_uuid_1")

    assert cart.data["items"] == items
    assert len(cart.data["items"]) == 2


@pytest.mark.django_db
def test_reads_empty_cart():
    _insert_cart("cart_client_uuid_2", [])

    cart = Cart.objects.get(pk="cart_client_uuid_2")

    assert cart.data["items"] == []
