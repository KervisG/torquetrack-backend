"""Aviso de cambio de precio en `GET /api/cart/` y `PUT /api/cart/`.

Cada item guardado lleva `priceAtAdd`, el precio del catálogo cuando el
producto entró al carrito; lo calcula el servidor y un `priceAtAdd` del body
se ignora. Si el precio actual difiere, la línea trae `priceChanged: true` y
`previousPrice`, y la respuesta suma un texto a `notices`. El aviso se acepta
solo con un `PUT` que manda `acknowledgePrices: true`: ese `PUT` mueve la
referencia al precio actual. Un `PUT` sin la marca conserva la referencia de
los productos que ya estaban. Un carrito viejo sin `priceAtAdd` toma el precio
actual como referencia la primera vez que se lee, sin avisar. En la fusión del
login manda la referencia del carrito de la cuenta. El cobro siempre usa el
precio actual (ver `apps/checkout/tests/test_checkout_view.py`). Sin
proveedores que mockear.
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.cart.models import Cart
from apps.catalog.models import Product
from tests.factories import DEFAULT_PASSWORD, create_user, guest_cart_client

PUMP = "gm-65-injection-pump-dorman-502550"
TURBO = "ford-73-powerstroke-turbo"
PUMP_TITLE = "6.5L Turbo Diesel Fuel Injection Pump"
PRODUCTS = {
    PUMP: {"id": PUMP, "title": PUMP_TITLE, "partNumber": "502-550", "price": 189.99},
    TURBO: {"id": TURBO, "title": "7.3L Powerstroke Turbo", "partNumber": "TP38", "price": 425.5},
}


@pytest.fixture(autouse=True)
def _catalog(db):
    for product_id, data in PRODUCTS.items():
        Product.objects.create(id=product_id, data=data)


def _set_price(product_id, price):
    Product.objects.filter(pk=product_id).update(data={**PRODUCTS[product_id], "price": price})


def _put(client, items, **extra):
    return client.put("/api/cart/", {"items": items, **extra}, format="json")


def _line(body, product_id):
    return next(line for line in body["items"] if line["id"] == product_id)


def _stored_reference(product_id):
    item = next(item for item in Cart.objects.get().data["items"] if item["id"] == product_id)
    return item.get("priceAtAdd")


@pytest.mark.django_db
def test_adding_a_product_stores_the_current_catalog_price_as_reference():
    client = APIClient()

    body = _put(client, [{"id": PUMP, "qty": 1}]).json()

    assert _stored_reference(PUMP) == 189.99
    assert _line(body, PUMP)["priceChanged"] is False
    assert "previousPrice" not in _line(body, PUMP)
    assert body["notices"] == []


@pytest.mark.django_db
def test_a_price_increase_is_announced_with_both_amounts():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])
    _set_price(PUMP, 200)

    body = client.get("/api/cart/").json()

    line = _line(body, PUMP)
    assert line["price"] == 200.0
    assert line["priceChanged"] is True
    assert line["previousPrice"] == 189.99
    assert body["notices"] == [
        f"The price of {PUMP_TITLE} has changed from $189.99 to $200.00."
    ]
    # El total usa el precio actual, nunca la referencia.
    assert body["subtotal"] == 200.0


@pytest.mark.django_db
def test_a_price_decrease_is_announced_too():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 2}])
    _set_price(PUMP, 150.5)

    body = client.get("/api/cart/").json()

    assert _line(body, PUMP)["previousPrice"] == 189.99
    assert body["notices"] == [
        f"The price of {PUMP_TITLE} has changed from $189.99 to $150.50."
    ]
    assert body["subtotal"] == 301.0


@pytest.mark.django_db
def test_an_unchanged_price_has_no_notice():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}, {"id": TURBO, "qty": 1}])
    _set_price(TURBO, 425.5)

    body = client.get("/api/cart/").json()

    assert body["notices"] == []
    assert [line["priceChanged"] for line in body["items"]] == [False, False]


@pytest.mark.django_db
def test_notice_amounts_use_thousands_separators():
    client = APIClient()
    _set_price(PUMP, 1189.99)
    _put(client, [{"id": PUMP, "qty": 1}])
    _set_price(PUMP, 1200)

    body = client.get("/api/cart/").json()

    assert body["notices"] == [
        f"The price of {PUMP_TITLE} has changed from $1,189.99 to $1,200.00."
    ]


@pytest.mark.django_db
def test_a_price_at_add_in_the_body_is_ignored():
    client = APIClient()

    body = _put(client, [{"id": PUMP, "qty": 1, "priceAtAdd": 1.0, "previousPrice": 1.0}]).json()

    assert _stored_reference(PUMP) == 189.99
    assert body["notices"] == []


@pytest.mark.django_db
def test_a_put_without_acknowledgement_keeps_the_reference_of_existing_products():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])
    _set_price(PUMP, 200)

    body = _put(client, [{"id": PUMP, "qty": 3}, {"id": TURBO, "qty": 1}]).json()

    # El aviso sigue hasta que el cliente lo acepte; el producto nuevo toma el
    # precio actual como referencia.
    assert body["notices"] == [
        f"The price of {PUMP_TITLE} has changed from $189.99 to $200.00."
    ]
    assert _line(body, TURBO)["priceChanged"] is False
    assert _stored_reference(PUMP) == 189.99
    assert _stored_reference(TURBO) == 425.5


@pytest.mark.django_db
def test_acknowledging_moves_the_reference_to_the_current_price():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])
    _set_price(PUMP, 200)

    body = _put(client, [{"id": PUMP, "qty": 1}], acknowledgePrices=True).json()

    assert body["notices"] == []
    assert _line(body, PUMP)["priceChanged"] is False
    assert _stored_reference(PUMP) == 200.0
    assert client.get("/api/cart/").json()["notices"] == []


@pytest.mark.django_db
@pytest.mark.parametrize("flag", ["true", 1, "yes", None])
def test_only_a_boolean_true_acknowledges(flag):
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])
    _set_price(PUMP, 200)

    body = _put(client, [{"id": PUMP, "qty": 1}], acknowledgePrices=flag).json()

    assert len(body["notices"]) == 1
    assert _stored_reference(PUMP) == 189.99


@pytest.mark.django_db
def test_a_new_price_change_after_acknowledging_is_announced_again():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])
    _set_price(PUMP, 200)
    _put(client, [{"id": PUMP, "qty": 1}], acknowledgePrices=True)
    _set_price(PUMP, 210)

    body = client.get("/api/cart/").json()

    assert body["notices"] == [
        f"The price of {PUMP_TITLE} has changed from $200.00 to $210.00."
    ]


@pytest.mark.django_db
def test_removing_and_adding_again_takes_the_current_price():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}, {"id": TURBO, "qty": 1}])
    _set_price(PUMP, 200)
    _put(client, [{"id": TURBO, "qty": 1}])

    body = _put(client, [{"id": TURBO, "qty": 1}, {"id": PUMP, "qty": 1}]).json()

    assert body["notices"] == []
    assert _stored_reference(PUMP) == 200.0


@pytest.mark.django_db
def test_an_unpriced_product_has_no_notice_and_keeps_its_reference():
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])
    _set_price(PUMP, 0)

    body = client.get("/api/cart/").json()

    assert _line(body, PUMP)["price"] is None
    assert _line(body, PUMP)["priceChanged"] is False
    assert body["notices"] == []
    assert _stored_reference(PUMP) == 189.99


@pytest.mark.django_db
def test_an_old_cart_without_references_takes_the_current_price_silently():
    stale = timezone.now() - timedelta(hours=2)
    Cart.objects.create(
        id="cart_legacy",
        data={"items": [{"id": PUMP, "qty": 1}], "stage": "CHECKOUT", "orderId": "OID1"},
        updated_at=stale,
    )
    client = guest_cart_client("cart_legacy")

    body = client.get("/api/cart/").json()

    assert body["notices"] == []
    cart = Cart.objects.get()
    assert cart.data["items"][0]["priceAtAdd"] == 189.99
    # Guardar la referencia no es actividad del cliente: no cambia la etapa ni
    # la fecha que usa el panel para marcar un carrito abandonado.
    assert cart.data["stage"] == "CHECKOUT"
    assert cart.data["orderId"] == "OID1"
    assert cart.updated_at == stale

    _set_price(PUMP, 200)
    assert client.get("/api/cart/").json()["notices"] == [
        f"The price of {PUMP_TITLE} has changed from $189.99 to $200.00."
    ]


@pytest.mark.django_db
def test_an_old_cart_line_without_reference_is_not_announced_on_put():
    Cart.objects.create(id="cart_legacy_put", data={"items": [{"id": PUMP, "qty": 1}]})
    client = guest_cart_client("cart_legacy_put")

    body = _put(client, [{"id": PUMP, "qty": 2}]).json()

    assert body["notices"] == []
    assert _stored_reference(PUMP) == 189.99


# --- fusión del login --------------------------------------------------------


def _login_with_guest_cart(email, guest_items):
    client = APIClient()
    assert _put(client, guest_items).status_code == 200
    response = client.post(
        "/api/login/", {"email": email, "password": DEFAULT_PASSWORD}, format="json"
    )
    assert response.status_code == 200
    return client


@pytest.mark.django_db
def test_merge_keeps_the_account_reference_for_a_product_in_both_carts():
    user = create_user("U_REF_MERGE", email="ref@example.com", password=DEFAULT_PASSWORD)
    Cart.objects.create(
        id="cart_account",
        user=user,
        data={"items": [{"id": PUMP, "qty": 1, "priceAtAdd": 150.0}], "stage": "CART"},
    )

    client = _login_with_guest_cart("ref@example.com", [{"id": PUMP, "qty": 1}])

    assert _stored_reference(PUMP) == 150.0
    assert client.get("/api/cart/").json()["notices"] == [
        f"The price of {PUMP_TITLE} has changed from $150.00 to $189.99."
    ]


@pytest.mark.django_db
def test_merge_keeps_the_guest_reference_of_a_product_only_in_the_guest_cart():
    user = create_user("U_REF_GUEST", email="guest-ref@example.com", password=DEFAULT_PASSWORD)
    Cart.objects.create(
        id="cart_account",
        user=user,
        data={"items": [{"id": TURBO, "qty": 1, "priceAtAdd": 425.5}], "stage": "CART"},
    )
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])
    _set_price(PUMP, 200)

    client.post(
        "/api/login/", {"email": "guest-ref@example.com", "password": DEFAULT_PASSWORD},
        format="json",
    )

    assert _stored_reference(PUMP) == 189.99
    assert _stored_reference(TURBO) == 425.5
    assert client.get("/api/cart/").json()["notices"] == [
        f"The price of {PUMP_TITLE} has changed from $189.99 to $200.00."
    ]


@pytest.mark.django_db
def test_merge_uses_the_guest_reference_when_the_account_line_has_none():
    user = create_user("U_REF_OLD", email="old-ref@example.com", password=DEFAULT_PASSWORD)
    Cart.objects.create(
        id="cart_account", user=user, data={"items": [{"id": PUMP, "qty": 1}], "stage": "CART"}
    )
    client = APIClient()
    _put(client, [{"id": PUMP, "qty": 1}])
    _set_price(PUMP, 200)

    client.post(
        "/api/login/", {"email": "old-ref@example.com", "password": DEFAULT_PASSWORD},
        format="json",
    )

    assert Cart.objects.get().data["items"][0]["qty"] == 2
    assert _stored_reference(PUMP) == 189.99
