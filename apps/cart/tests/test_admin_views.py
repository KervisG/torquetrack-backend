"""`GET /api/admin/carts` (task 7.3), pinned against
`app/api/admin/carts/route.ts`.
"""
import json
from importlib import import_module

import pytest
from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.cart.models import Cart


def _insert_user(user_id, role="authorized", permissions=None, active=True):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into users (id, username, password_hash, role, active, "
            "permissions) values (%s, %s, %s, %s, %s, %s::jsonb)",
            [
                user_id,
                f"{user_id}@example.com",
                "scrypt$salt$hash",
                role,
                active,
                json.dumps(permissions or []),
            ],
        )


def _admin_client(user_id):
    engine = import_module(settings.SESSION_ENGINE)
    store = engine.SessionStore()
    store["user_id"] = user_id
    store.save()
    client = APIClient()
    client.cookies["tt_admin"] = store.session_key
    return client


@pytest.mark.django_db
def test_returns_403_without_carts_view_permission():
    _insert_user("usr_carts_no_perm", permissions=[])
    client = _admin_client("usr_carts_no_perm")

    response = client.get("/api/admin/carts/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_deletes_carts_with_no_items_before_listing():
    _insert_user("usr_carts", permissions=["carts.view"])
    Cart.objects.create(id="cart_empty", data={"items": []}, updated_at=timezone.now())
    Cart.objects.create(id="cart_no_items_key", data={}, updated_at=timezone.now())
    Cart.objects.create(
        id="cart_with_item",
        data={"items": [{"id": "p1", "qty": 1}]},
        updated_at=timezone.now(),
    )
    client = _admin_client("usr_carts")

    response = client.get("/api/admin/carts/")

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body] == ["cart_with_item"]
    assert not Cart.objects.filter(pk="cart_empty").exists()
    assert not Cart.objects.filter(pk="cart_no_items_key").exists()


@pytest.mark.django_db
def test_cart_stage_status_is_active_within_30_minutes():
    _insert_user("usr_carts2", permissions=["carts.view"])
    Cart.objects.create(
        id="cart_recent",
        data={"items": [{"id": "p1", "qty": 1}], "stage": "CART"},
        updated_at=timezone.now(),
    )
    client = _admin_client("usr_carts2")

    response = client.get("/api/admin/carts/")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["status"] == "ACTIVE"


@pytest.mark.django_db
def test_cart_stage_status_is_abandoned_after_30_minutes():
    _insert_user("usr_carts3", permissions=["carts.view"])
    Cart.objects.create(
        id="cart_old",
        data={"items": [{"id": "p1", "qty": 1}], "stage": "CART"},
        updated_at=timezone.now() - timezone.timedelta(minutes=45),
    )
    client = _admin_client("usr_carts3")

    response = client.get("/api/admin/carts/")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["status"] == "ABANDONED"


@pytest.mark.django_db
def test_non_cart_stage_status_uses_stage_verbatim():
    _insert_user("usr_carts4", permissions=["carts.view"])
    Cart.objects.create(
        id="cart_checkout",
        data={"items": [{"id": "p1", "qty": 1}], "stage": "CHECKOUT"},
        updated_at=timezone.now() - timezone.timedelta(hours=2),
    )
    client = _admin_client("usr_carts4")

    response = client.get("/api/admin/carts/")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["status"] == "CHECKOUT"
