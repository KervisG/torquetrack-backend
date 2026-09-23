"""`GET /api/admin/carts/` con `carts.view`. Sin proveedores que mockear."""
import pytest
from django.utils import timezone

from apps.cart.models import Cart
from tests.factories import create_staff_user, session_client


def _insert_user(user_id, permissions=None, active=True, full_access=False):
    create_staff_user(
        user_id, permissions=permissions, active=active, full_access=full_access
    )


def _admin_client(user_id):
    client, _ = session_client(user_id)
    return client


@pytest.mark.django_db
def test_returns_403_without_carts_view_permission():
    _insert_user("usr_carts_no_perm", permissions=[])
    client = _admin_client("usr_carts_no_perm")

    response = client.get("/api/admin/carts/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_listing_omits_carts_with_no_items_without_deleting_them():
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
    # Un GET nunca escribe: la limpieza es `manage.py purge_carts`.
    assert Cart.objects.count() == 3


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
