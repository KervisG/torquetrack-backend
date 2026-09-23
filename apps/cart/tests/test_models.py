"""Tests del modelo `Cart` (tabla `carts`).

Solo prueban la lectura y escritura del modelo; el upsert por UUID y el
borrado del carrito vacío se prueban en `test_views.py` y `test_services.py`.
"""

import pytest

from apps.cart.models import Cart


def _insert_cart(cart_id, items):
    Cart.objects.create(id=cart_id, data={"items": items})


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
