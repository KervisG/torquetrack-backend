"""`GET /api/cart/` y `PUT /api/cart/`.

El backend es la fuente de verdad del carrito. Con sesión autenticada el
carrito es el de la cuenta (`Cart.user`), así que se ve igual desde cualquier
dispositivo; sin cuenta es el de la sesión anónima (`request.session["cart_id"]`)
y un `cartId` del body se ignora. `PUT` reemplaza los items `[{id, qty}]`:
producto activo existente, cantidad entera de 1 a 99, sin repetidos. Cada
respuesta reprecia desde el catálogo e ignora cualquier precio del cliente.
Un `PUT` con `items` vacío borra el carrito. Sin proveedores que mockear.
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.cart.models import Cart
from apps.cart.services import CART_SESSION_KEY
from apps.catalog.models import Product
from tests.factories import create_user, guest_cart_client, session_client

PUMP = "gm-65-injection-pump-dorman-502550"
TURBO = "ford-73-powerstroke-turbo"
PRODUCTS = {
    PUMP: {
        "id": PUMP,
        "title": "6.5L Turbo Diesel Fuel Injection Pump",
        "partNumber": "502-550",
        "price": 189.99,
        "coreCharge": 50.0,
    },
    TURBO: {
        "id": TURBO,
        "title": "7.3L Powerstroke Turbo",
        "partNumber": "TP38",
        "price": 425.5,
        "coreCharge": 0,
    },
}


@pytest.fixture(autouse=True)
def _catalog(db):
    for product_id, data in PRODUCTS.items():
        Product.objects.create(id=product_id, data=data)


def _put(client, items, **extra):
    return client.put("/api/cart/", {"items": items, **extra}, format="json")


def _get(client):
    return client.get("/api/cart/")


def _user_client(user_id, **kwargs):
    create_user(user_id)
    client, _ = session_client(user_id, **kwargs)
    return client


@pytest.mark.django_db
def test_guest_without_a_cart_reads_an_empty_cart():
    response = _get(APIClient())

    assert response.status_code == 200
    assert response.json() == {"items": [], "subtotal": 0.0, "core": 0.0, "notices": []}
    assert not Cart.objects.exists()


@pytest.mark.django_db
def test_guest_put_creates_a_session_cart_and_returns_repriced_lines():
    client = APIClient()

    response = _put(client, [{"id": PUMP, "qty": 2}])

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": PUMP,
                "qty": 2,
                "title": "6.5L Turbo Diesel Fuel Injection Pump",
                "partNumber": "502-550",
                "price": 189.99,
                "coreCharge": 50.0,
                "lineTotal": 379.98,
                "priceChanged": False,
            }
        ],
        "subtotal": 379.98,
        "core": 100.0,
        "notices": [],
    }
    cart = Cart.objects.get()
    assert client.session[CART_SESSION_KEY] == cart.pk
    assert cart.user_id is None
    assert _get(client).json()["items"][0]["qty"] == 2


@pytest.mark.django_db
def test_prices_come_from_the_catalog_and_ignore_the_client():
    client = APIClient()

    response = _put(
        client, [{"id": PUMP, "qty": 1, "price": 0.01, "unitPrice": 0.01, "coreCharge": 0}]
    )

    line = response.json()["items"][0]
    assert line["price"] == 189.99
    assert line["coreCharge"] == 50.0
    assert response.json()["subtotal"] == 189.99
    # Lo guardado tampoco conserva el precio del cliente.
    assert "price" not in Cart.objects.get().data["items"][0]
    assert "unitPrice" not in Cart.objects.get().data["items"][0]


@pytest.mark.django_db
def test_reading_reprices_with_the_current_catalog_price():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])
    Product.objects.filter(pk=PUMP).update(data={**PRODUCTS[PUMP], "price": 200})

    body = _get(client).json()

    assert body["items"][0]["price"] == 200.0
    assert body["subtotal"] == 200.0


@pytest.mark.django_db
def test_reading_omits_a_product_that_was_deactivated_after_it_was_added():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}, {"id": TURBO, "qty": 1}])
    Product.objects.filter(pk=PUMP).update(active=False)

    body = _get(client).json()

    assert [line["id"] for line in body["items"]] == [TURBO]
    assert body["subtotal"] == 425.5


@pytest.mark.django_db
def test_an_unpriced_product_is_listed_without_a_price_and_left_out_of_the_subtotal():
    Product.objects.filter(pk=TURBO).update(data={**PRODUCTS[TURBO], "price": 0})
    client = APIClient()

    body = _put(client, [{"id": PUMP, "qty": 1}, {"id": TURBO, "qty": 1}]).json()

    assert [line["id"] for line in body["items"]] == [PUMP, TURBO]
    assert body["items"][1]["price"] is None
    assert body["items"][1]["lineTotal"] is None
    assert body["subtotal"] == 189.99


@pytest.mark.django_db
def test_put_replaces_the_items_of_the_same_session_cart():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])

    body = _put(client, [{"id": TURBO, "qty": 3}]).json()

    assert [(line["id"], line["qty"]) for line in body["items"]] == [(TURBO, 3)]
    assert Cart.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("qty", [0, -1, 100, 1.5, "abc", None, True])
def test_invalid_quantity_is_rejected(qty):
    client = APIClient()

    response = _put(client, [{"id": PUMP, "qty": qty}])

    assert response.status_code == 400
    assert response.json() == {
        "error": "Item quantity must be a whole number from 1 to 99"
    }
    assert not Cart.objects.exists()


@pytest.mark.django_db
def test_a_missing_quantity_is_rejected():
    response = _put(APIClient(), [{"id": PUMP}])

    assert response.status_code == 400
    assert response.json()["error"] == "Item quantity must be a whole number from 1 to 99"


@pytest.mark.django_db
def test_an_inactive_product_is_rejected():
    Product.objects.filter(pk=PUMP).update(active=False)

    response = _put(APIClient(), [{"id": PUMP, "qty": 1}])

    assert response.status_code == 400
    assert response.json() == {"error": f"These products are not available: {PUMP}"}
    assert not Cart.objects.exists()


@pytest.mark.django_db
def test_an_unknown_product_is_rejected_and_the_cart_is_kept():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])

    response = _put(client, [{"id": PUMP, "qty": 2}, {"id": "no-such-part", "qty": 1}])

    assert response.status_code == 400
    assert response.json() == {"error": "These products are not available: no-such-part"}
    assert Cart.objects.get().data["items"][0]["qty"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"items": "p1"},
        {"items": [PUMP]},
        {"items": [{"qty": 1}]},
        {"items": [{"id": 3, "qty": 1}]},
    ],
    ids=["missing", "string", "not-objects", "no-id", "non-string-id"],
)
def test_malformed_items_are_rejected(body):
    response = APIClient().put("/api/cart/", body, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": "Items must be a list of objects with an id and qty"}


@pytest.mark.django_db
def test_a_repeated_product_is_rejected():
    response = _put(APIClient(), [{"id": PUMP, "qty": 1}, {"id": PUMP, "qty": 2}])

    assert response.status_code == 400
    assert response.json() == {"error": "Each product can appear only once in the cart"}


@pytest.mark.django_db
def test_too_many_lines_are_rejected():
    items = [{"id": f"part-{n}", "qty": 1} for n in range(101)]

    response = _put(APIClient(), items)

    assert response.status_code == 400
    assert response.json() == {"error": "A cart can hold at most 100 different products"}


@pytest.mark.django_db
def test_form_encoded_body_is_rejected():
    response = APIClient().put(
        "/api/cart/", "items=1", content_type="application/x-www-form-urlencoded"
    )

    assert response.status_code == 415


@pytest.mark.django_db
def test_empty_items_deletes_the_session_cart():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])

    response = _put(client, [])

    assert response.status_code == 200
    assert response.json() == {"items": [], "subtotal": 0.0, "core": 0.0, "notices": []}
    assert not Cart.objects.exists()


@pytest.mark.django_db
def test_body_cart_id_of_another_cart_is_ignored():
    Cart.objects.create(id="cart_victim", data={"items": [{"id": PUMP, "qty": 5}]})
    client = APIClient()

    _put(client, [{"id": TURBO, "qty": 1}], cartId="cart_victim")
    _put(client, [], cartId="cart_victim")

    assert Cart.objects.get(pk="cart_victim").data == {"items": [{"id": PUMP, "qty": 5}]}


@pytest.mark.django_db
def test_a_guest_session_never_reads_an_account_cart():
    user = create_user("U_CART_OWNER")
    Cart.objects.create(id="cart_account", user=user, data={"items": [{"id": PUMP, "qty": 1}]})

    body = _get(guest_cart_client("cart_account")).json()

    assert body["items"] == []


@pytest.mark.django_db
def test_signed_in_cart_is_the_account_cart_on_every_device():
    laptop = _user_client("U_CART_DEVICES")
    phone, _ = session_client("U_CART_DEVICES")

    _put(laptop, [{"id": PUMP, "qty": 2}])
    body = _get(phone).json()

    assert [(line["id"], line["qty"]) for line in body["items"]] == [(PUMP, 2)]
    cart = Cart.objects.get()
    assert cart.user_id == "U_CART_DEVICES"
    assert CART_SESSION_KEY not in laptop.session


@pytest.mark.django_db
def test_signed_in_changes_from_another_device_update_the_same_cart():
    laptop = _user_client("U_CART_TWO")
    phone, _ = session_client("U_CART_TWO")
    _put(laptop, [{"id": PUMP, "qty": 2}])

    _put(phone, [{"id": TURBO, "qty": 1}])

    assert Cart.objects.count() == 1
    assert [line["id"] for line in _get(laptop).json()["items"]] == [TURBO]


@pytest.mark.django_db
def test_signed_in_put_requires_csrf():
    client = _user_client("U_CART_CSRF", enforce_csrf=True)

    response = _put(client, [{"id": PUMP, "qty": 1}])

    assert response.status_code == 403
    assert not Cart.objects.exists()


@pytest.fixture
def _clear_throttle_cache(db):
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
@pytest.mark.usefixtures("_clear_throttle_cache")
def test_logout_keeps_the_account_cart_and_starts_an_empty_session():
    create_user("U_CART_OUT", email="out@example.com", password="diesel-pass-123")
    client = APIClient()
    client.post(
        "/api/login/", {"email": "out@example.com", "password": "diesel-pass-123"}, format="json"
    )
    _put(client, [{"id": PUMP, "qty": 3}])

    client.post("/api/logout/")

    assert _get(client).json()["items"] == []
    assert Cart.objects.get().user_id == "U_CART_OUT"
    other, _ = session_client("U_CART_OUT")
    assert _get(other).json()["items"][0]["qty"] == 3
