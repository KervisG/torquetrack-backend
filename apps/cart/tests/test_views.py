"""Un array `items` vacío o ausente borra el carrito en vez de guardarlo."""

import pytest
from rest_framework.test import APIClient

from apps.cart.models import Cart


def _read_cart_row(cart_id):
    cart = Cart.objects.filter(pk=cart_id).first()
    return None if cart is None else cart.data


def _insert_cart(cart_id, data):
    Cart.objects.create(id=cart_id, data=data)


@pytest.mark.django_db
def test_sync_creates_cart_with_generated_id_when_cart_id_missing():
    response = APIClient().post(
        "/api/cart/sync/",
        {"items": [{"id": "gm-65-injection-pump-dorman-502550", "qty": 1}]},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "ACTIVE"
    assert body["cartId"]
    assert _read_cart_row(body["cartId"]) is not None


@pytest.mark.django_db
def test_sync_upserts_existing_cart_by_client_uuid():
    _insert_cart("cart_client_uuid_1", {"items": [], "stage": "CART"})

    response = APIClient().post(
        "/api/cart/sync/",
        {
            "cartId": "cart_client_uuid_1",
            "items": [{"id": "ford-73-powerstroke-turbo", "qty": 2}],
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cartId"] == "cart_client_uuid_1"
    stored = _read_cart_row("cart_client_uuid_1")
    assert stored["items"] == [{"id": "ford-73-powerstroke-turbo", "qty": 2}]


@pytest.mark.django_db
def test_sync_deletes_row_and_returns_empty_status_when_items_empty():
    _insert_cart("cart_client_uuid_2", {"items": [{"id": "x", "qty": 1}]})

    response = APIClient().post(
        "/api/cart/sync/",
        {"cartId": "cart_client_uuid_2", "items": []},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "cartId": "cart_client_uuid_2", "status": "EMPTY", "removed": True}
    assert _read_cart_row("cart_client_uuid_2") is None


@pytest.mark.django_db
def test_sync_deleting_a_cart_that_never_existed_is_idempotent():
    response = APIClient().post(
        "/api/cart/sync/",
        {"cartId": "cart_never_existed", "items": []},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["removed"] is True
    assert _read_cart_row("cart_never_existed") is None


@pytest.mark.django_db
def test_sync_non_cart_stage_sets_status_to_stage_value():
    response = APIClient().post(
        "/api/cart/sync/",
        {
            "cartId": "cart_client_uuid_3",
            "stage": "checkout",
            "items": [{"id": "x", "qty": 1}],
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CHECKOUT"
    stored = _read_cart_row("cart_client_uuid_3")
    assert stored["stage"] == "CHECKOUT"
    assert stored["status"] == "CHECKOUT"
