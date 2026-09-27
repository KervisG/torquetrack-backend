"""`POST /api/cart/sync/`.

El carrito pertenece a la sesión: su id vive en `request.session["cart_id"]` y
el `cartId` del body se ignora, así nadie que conozca el id de otro carrito
puede reescribirlo ni borrarlo. Un array `items` vacío o ausente borra el
carrito de la sesión en vez de guardarlo. Sin proveedores que mockear.
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.cart.models import Cart
from apps.cart.services import CART_SESSION_KEY
from tests.factories import create_user, guest_cart_client, session_client

ITEMS = [{"id": "gm-65-injection-pump-dorman-502550", "qty": 1}]


def _read_cart_row(cart_id):
    cart = Cart.objects.filter(pk=cart_id).first()
    return None if cart is None else cart.data


def _insert_cart(cart_id, data):
    Cart.objects.create(id=cart_id, data=data)


def _sync(client, body):
    return client.post("/api/cart/sync/", body, format="json")


@pytest.mark.django_db
def test_first_sync_creates_a_cart_and_binds_it_to_the_session():
    client = APIClient()

    response = _sync(client, {"items": ITEMS})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "ACTIVE"
    assert client.session[CART_SESSION_KEY] == body["cartId"]
    assert _read_cart_row(body["cartId"])["items"] == ITEMS


@pytest.mark.django_db
def test_later_syncs_update_the_same_session_cart():
    client = APIClient()
    first = _sync(client, {"items": ITEMS}).json()["cartId"]

    second = _sync(client, {"items": [{"id": "ford-73-powerstroke-turbo", "qty": 2}]})

    assert second.json()["cartId"] == first
    assert Cart.objects.count() == 1
    assert _read_cart_row(first)["items"] == [{"id": "ford-73-powerstroke-turbo", "qty": 2}]


@pytest.mark.django_db
def test_body_cart_id_of_another_cart_is_ignored():
    _insert_cart("cart_victim", {"items": ITEMS, "stage": "CART"})
    client = APIClient()

    response = _sync(client, {"cartId": "cart_victim", "items": [{"id": "x", "qty": 9}]})

    assert response.status_code == 200
    assert response.json()["cartId"] != "cart_victim"
    assert _read_cart_row("cart_victim") == {"items": ITEMS, "stage": "CART"}


@pytest.mark.django_db
def test_empty_items_with_a_foreign_cart_id_does_not_delete_it():
    _insert_cart("cart_victim", {"items": ITEMS})

    response = _sync(APIClient(), {"cartId": "cart_victim", "items": []})

    assert response.status_code == 200
    assert response.json()["status"] == "EMPTY"
    assert _read_cart_row("cart_victim") == {"items": ITEMS}


@pytest.mark.django_db
def test_stored_data_never_keeps_the_body_cart_id():
    client = APIClient()

    body = _sync(client, {"cartId": "cart_forged", "items": ITEMS}).json()

    assert _read_cart_row(body["cartId"])["cartId"] == body["cartId"]
    assert not Cart.objects.filter(pk="cart_forged").exists()


@pytest.mark.django_db
def test_empty_items_deletes_the_session_cart():
    _insert_cart("cart_mine", {"items": ITEMS})
    client = guest_cart_client("cart_mine")

    response = _sync(client, {"items": []})

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "cartId": "cart_mine",
        "status": "EMPTY",
        "removed": True,
    }
    assert _read_cart_row("cart_mine") is None


@pytest.mark.django_db
def test_emptying_without_a_session_cart_creates_nothing():
    client = APIClient()

    response = _sync(client, {"items": []})

    assert response.status_code == 200
    assert response.json()["removed"] is True
    assert not Cart.objects.exists()
    assert CART_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_non_cart_stage_sets_status_to_stage_value():
    client = guest_cart_client("cart_mine")

    response = _sync(client, {"stage": "checkout", "items": ITEMS})

    assert response.status_code == 200
    assert response.json()["status"] == "CHECKOUT"
    stored = _read_cart_row("cart_mine")
    assert stored["stage"] == "CHECKOUT"
    assert stored["status"] == "CHECKOUT"


@pytest.mark.django_db
def test_signed_in_sync_requires_csrf():
    create_user("U_CART_PAT")
    client, _ = session_client("U_CART_PAT", enforce_csrf=True)

    response = _sync(client, {"items": ITEMS})

    assert response.status_code == 403
    assert not Cart.objects.exists()


@pytest.fixture
def _clear_throttle_cache(db):
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
@pytest.mark.usefixtures("_clear_throttle_cache")
def test_login_keeps_the_guest_cart_bound_to_the_new_session():
    create_user("U_CART_LOGIN", email="pat@example.com", password="diesel-pass-123")
    client = APIClient()
    cart_id = _sync(client, {"items": ITEMS}).json()["cartId"]

    login = client.post(
        "/api/login/",
        {"email": "pat@example.com", "password": "diesel-pass-123"},
        format="json",
    )

    assert login.status_code == 200
    assert client.session[CART_SESSION_KEY] == cart_id
