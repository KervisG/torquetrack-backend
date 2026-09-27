"""Fusión del carrito invitado con el de la cuenta al iniciar sesión.

La dispara la señal `user_logged_in` de Django (conectada en
`CartConfig.ready()`), así que cubre todo `login()`: `POST /api/login/`, la
activación del portal y `force_login`. Suma las cantidades del mismo producto
con tope 99, conserva los productos distintos y consume el carrito invitado
(sin duplicados). Es idempotente y serializa fusiones simultáneas bloqueando
la fila del usuario. Sin proveedores que mockear.
"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.cache import cache
from django.db import connections
from rest_framework.test import APIClient

from apps.authentication.models import User
from apps.cart.models import Cart
from apps.cart.services import CART_SESSION_KEY, merge_session_cart
from apps.catalog.models import Product
from tests.factories import DEFAULT_PASSWORD, create_user, session_client

PUMP = "pump"
TURBO = "turbo"
INJECTOR = "injector"


@pytest.fixture(autouse=True)
def _catalog(db):
    for product_id, price in [(PUMP, 100), (TURBO, 200), (INJECTOR, 50)]:
        Product.objects.create(
            id=product_id, data={"id": product_id, "title": product_id.title(), "price": price}
        )


@pytest.fixture(autouse=True)
def _clear_throttle_cache(db):
    cache.clear()
    yield
    cache.clear()


def _items(cart):
    return [(item["id"], item["qty"]) for item in cart.data["items"]]


def _guest_with_cart(items):
    client = APIClient()
    assert client.put("/api/cart/", {"items": items}, format="json").status_code == 200
    return client


def _account_cart(user, items):
    return Cart.objects.create(
        id=f"cart_{user.pk}", user=user, data={"items": items, "stage": "CART"}
    )


def _login(client, email):
    response = client.post(
        "/api/login/", {"email": email, "password": DEFAULT_PASSWORD}, format="json"
    )
    assert response.status_code == 200
    return response


@pytest.mark.django_db
def test_login_adopts_the_guest_cart_when_the_account_has_none():
    create_user("U_ADOPT", email="adopt@example.com", password=DEFAULT_PASSWORD)
    client = _guest_with_cart([{"id": PUMP, "qty": 2}])

    _login(client, "adopt@example.com")

    cart = Cart.objects.get()
    assert cart.user_id == "U_ADOPT"
    assert _items(cart) == [(PUMP, 2)]
    assert CART_SESSION_KEY not in client.session
    assert client.get("/api/cart/").json()["items"][0]["qty"] == 2


@pytest.mark.django_db
def test_login_sums_the_same_product_and_keeps_distinct_ones():
    user = create_user("U_MERGE", email="merge@example.com", password=DEFAULT_PASSWORD)
    _account_cart(user, [{"id": PUMP, "qty": 1}, {"id": TURBO, "qty": 1}])
    client = _guest_with_cart([{"id": PUMP, "qty": 2}, {"id": INJECTOR, "qty": 4}])

    _login(client, "merge@example.com")

    cart = Cart.objects.get()
    assert cart.user_id == "U_MERGE"
    assert _items(cart) == [(PUMP, 3), (TURBO, 1), (INJECTOR, 4)]
    body = client.get("/api/cart/").json()
    assert [(line["id"], line["qty"]) for line in body["items"]] == [
        (PUMP, 3),
        (TURBO, 1),
        (INJECTOR, 4),
    ]


@pytest.mark.django_db
def test_merged_quantities_are_capped_at_99():
    user = create_user("U_CAP", email="cap@example.com", password=DEFAULT_PASSWORD)
    _account_cart(user, [{"id": PUMP, "qty": 60}])
    client = _guest_with_cart([{"id": PUMP, "qty": 50}])

    _login(client, "cap@example.com")

    assert _items(Cart.objects.get()) == [(PUMP, 99)]


@pytest.mark.django_db
def test_merge_drops_products_that_are_no_longer_available():
    user = create_user("U_GONE", email="gone@example.com", password=DEFAULT_PASSWORD)
    _account_cart(user, [{"id": PUMP, "qty": 1}])
    client = _guest_with_cart([{"id": TURBO, "qty": 1}])
    Product.objects.filter(pk=TURBO).update(active=False)

    _login(client, "gone@example.com")

    assert _items(Cart.objects.get()) == [(PUMP, 1)]


@pytest.mark.django_db
def test_login_without_a_guest_cart_keeps_the_account_cart():
    user = create_user("U_KEEP", email="keep@example.com", password=DEFAULT_PASSWORD)
    _account_cart(user, [{"id": PUMP, "qty": 5}])

    _login(APIClient(), "keep@example.com")

    assert _items(Cart.objects.get()) == [(PUMP, 5)]


@pytest.mark.django_db
def test_merge_is_idempotent():
    user = create_user("U_TWICE", email="twice@example.com", password=DEFAULT_PASSWORD)
    _account_cart(user, [{"id": PUMP, "qty": 1}])
    client = _guest_with_cart([{"id": PUMP, "qty": 2}])
    guest_session = dict(client.session.items())

    _login(client, "twice@example.com")
    # Repetir la fusión con los datos de la sesión invitada no vuelve a sumar:
    # el carrito invitado ya se consumió.
    merge_session_cart(user, guest_session)
    _login(client, "twice@example.com")

    assert Cart.objects.count() == 1
    assert _items(Cart.objects.get()) == [(PUMP, 3)]


@pytest.mark.django_db
def test_a_guest_session_cannot_merge_an_account_cart_of_someone_else():
    owner = create_user("U_OWNER")
    _account_cart(owner, [{"id": PUMP, "qty": 7}])
    thief = create_user("U_THIEF")

    merge_session_cart(thief, {CART_SESSION_KEY: f"cart_{owner.pk}"})

    assert Cart.objects.get().user_id == "U_OWNER"
    assert not Cart.objects.filter(user=thief).exists()


@pytest.mark.django_db
def test_force_login_also_merges_through_the_signal():
    create_user("U_FORCE")
    guest = _guest_with_cart([{"id": PUMP, "qty": 1}])
    cart_id = guest.session[CART_SESSION_KEY]

    guest.force_login(User.objects.get(pk="U_FORCE"))

    assert Cart.objects.get(pk=cart_id).user_id == "U_FORCE"
    assert CART_SESSION_KEY not in guest.session


def _merge_in_thread(user_id, session):
    try:
        merge_session_cart(User.objects.get(pk=user_id), session)
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_concurrent_merges_of_the_same_guest_cart_add_it_once():
    user = create_user("U_RACE")
    _account_cart(user, [{"id": PUMP, "qty": 1}])
    Cart.objects.create(id="cart_guest", data={"items": [{"id": PUMP, "qty": 2}]})
    sessions = [{CART_SESSION_KEY: "cart_guest"} for _ in range(6)]

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda session: _merge_in_thread("U_RACE", session), sessions))

    assert Cart.objects.count() == 1
    assert _items(Cart.objects.get()) == [(PUMP, 3)]


@pytest.mark.django_db
def test_signed_in_session_client_sees_the_merged_cart_from_another_device():
    user = create_user("U_OTHER_DEVICE", email="dev@example.com", password=DEFAULT_PASSWORD)
    _account_cart(user, [{"id": TURBO, "qty": 1}])
    _login(_guest_with_cart([{"id": PUMP, "qty": 1}]), "dev@example.com")

    phone, _ = session_client("U_OTHER_DEVICE")

    ids = [line["id"] for line in phone.get("/api/cart/").json()["items"]]
    assert ids == [TURBO, PUMP]
