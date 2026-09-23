"""`list_admin_carts` borra primero los carritos vacíos.

Se borra el carrito cuando `items` falta, no es un array o es un array
vacío. Solo sobrevive un array con al menos un elemento.
"""
import pytest
from django.utils import timezone

from apps.cart.models import Cart
from apps.cart.services import list_admin_carts


@pytest.mark.django_db
@pytest.mark.parametrize(
    "data",
    [
        {},
        {"items": None},
        {"items": []},
        {"items": "p1"},
        {"items": 3},
        {"items": {"0": {"id": "p1"}}},
    ],
    ids=["missing", "json-null", "empty-array", "string", "number", "object"],
)
def test_deletes_carts_whose_items_are_missing_non_array_or_empty(data):
    Cart.objects.create(id="cart_empty", data=data, updated_at=timezone.now())

    rows = list_admin_carts()

    assert rows == []
    assert not Cart.objects.filter(pk="cart_empty").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "items", [[{"id": "p1", "qty": 1}], [None], [[]]], ids=["object", "null-element", "nested"]
)
def test_keeps_carts_with_a_non_empty_items_array(items):
    Cart.objects.create(id="cart_full", data={"items": items}, updated_at=timezone.now())

    rows = list_admin_carts()

    assert [row["id"] for row in rows] == ["cart_full"]
    assert Cart.objects.filter(pk="cart_full").exists()
