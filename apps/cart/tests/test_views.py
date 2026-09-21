"""`POST /api/cart/sync` (task 5.1), pinned against
`app/api/cart/sync/route.ts`.

Behavior preserved: upsert-by-client-UUID, `stage` normalizes to uppercase
(`status = "ACTIVE"` for stage `"CART"`, otherwise `status = stage`), and an
empty/missing `items` array deletes the row instead of upserting it.
"""
import json

import pytest
from django.db import connection
from rest_framework.test import APIClient


def _read_cart_row(cart_id):
    with connection.cursor() as cursor:
        cursor.execute("select data from carts where id = %s", [cart_id])
        row = cursor.fetchone()
        if row is None:
            return None
        return row[0] if isinstance(row[0], dict) else json.loads(row[0])


def _insert_cart(cart_id, data):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into carts (id, data) values (%s, %s)",
            [cart_id, json.dumps(data)],
        )


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
