
import logging

import pytest
from rest_framework.test import APIClient

from apps.cart.models import Cart
from apps.catalog.models import Product
from apps.checkout.models import Order, OrderStatus, Payment
from apps.customers.models import Customer
from apps.integrations.exceptions import ProviderError
from tests.factories import CHECKOUT_CONTACT, create_customer, guest_cart_client
from tests.fakes import quote_shipping

CREATE_SESSION = "apps.integrations.payments.stripe.create_checkout_session"

PRODUCT_ID = "gm-65-injection-pump-dorman-502550"
PRODUCT_DATA = {
    "id": PRODUCT_ID,
    "title": "6.5L Turbo Diesel Fuel Injection Pump",
    "partNumber": "502-550",
    "price": 189.99,
    "coreCharge": 50.0,
    "make": "Chevrolet / GMC",
    "yearFrom": 1994,
    "yearTo": 2000,
    "engineFamily": "6.5",
}
VEHICLE = {"make": "Chevrolet", "year": 1996, "engine": "6.5"}
SHIPPING_RATE = 12.5


def _insert_product(product_id=PRODUCT_ID, data=None, active=True):
    Product.objects.create(id=product_id, data=data or PRODUCT_DATA, active=active)


def _insert_customer(customer_id, email, tax_status="NOT SUBMITTED", data=None):
    create_customer(customer_id, email=email, tax_status=tax_status, data=data or {})


def _insert_cart(cart_id, data):
    Cart.objects.create(id=cart_id, data=data)


def _fake_session(session_id="cs_test_123", url="https://checkout.stripe.com/pay/cs_test_123"):
    return {"id": session_id, "url": url}


@pytest.fixture(autouse=True)
def _stripe_secret_key(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_fake_not_real"
    settings.TAXJAR_API_KEY = ""
    return settings


@pytest.fixture
def shipping(monkeypatch, settings):
    return quote_shipping(
        monkeypatch,
        settings,
        zip_code="33701",
        rate=SHIPPING_RATE,
        items=[{"id": PRODUCT_ID, "qty": 1}],
    )


def _body(shipping, **overrides):
    """Un `customer` del override se suma al contacto válido (`CHECKOUT_CONTACT`)."""
    customer = overrides.pop("customer", {"state": "FL", "zip": "33701"})
    body = {
        "items": [{"id": PRODUCT_ID, "qty": 1}],
        "vehicle": VEHICLE,
        "customer": {**CHECKOUT_CONTACT, **customer} if isinstance(customer, dict) else customer,
        "shipping": shipping,
    }
    body.update(overrides)
    return body


def _post(body, client=None):
    return (client or APIClient()).post("/api/checkout/", body, format="json")


@pytest.mark.django_db
def test_returns_503_when_stripe_not_configured(settings):
    settings.STRIPE_SECRET_KEY = ""

    response = _post({"items": []})

    assert response.status_code == 503
    assert "STRIPE_SECRET_KEY" in response.json()["error"]


@pytest.mark.django_db
def test_returns_400_when_cart_is_empty():
    response = _post({"items": []})

    assert response.status_code == 400
    assert response.json() == {"error": "Cart is empty"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "items",
    [["gm-65"], [1], [None], [[PRODUCT_ID]], "gm-65", {"id": PRODUCT_ID}],
)
def test_returns_400_when_items_are_not_a_list_of_objects(items, monkeypatch):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post({"items": items, "vehicle": VEHICLE})

    assert response.status_code == 400
    assert "error" in response.json()
    assert not Order.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["customer", "vehicle"])
def test_returns_400_when_customer_or_vehicle_is_not_an_object(field, shipping):
    _insert_product()

    response = _post(_body(shipping, **{field: "not-an-object"}))

    assert response.status_code == 400
    assert not Order.objects.exists()


@pytest.mark.django_db
def test_returns_400_when_no_valid_products_in_cart():
    response = _post({"items": [{"id": "does-not-exist", "qty": 1}]})

    assert response.status_code == 400
    assert response.json()["error"] == "No valid products in cart"


@pytest.mark.django_db
@pytest.mark.parametrize("price", [0, -5, None])
def test_returns_409_when_a_catalog_price_is_not_positive(price, monkeypatch, shipping):
    # Un producto sin precio en el catálogo se cobraría gratis en Stripe.
    _insert_product(data={**PRODUCT_DATA, "price": price})

    def _boom(**kwargs):
        raise AssertionError("Stripe must not be called for an unpriced item")

    monkeypatch.setattr(CREATE_SESSION, _boom)

    response = _post(_body(shipping))

    assert response.status_code == 409
    assert response.json() == {
        "error": "These items have no valid price and cannot be purchased online: 502-550"
    }
    assert not Order.objects.exists()


@pytest.mark.django_db
def test_reprices_from_db_ignoring_client_submitted_price(monkeypatch, settings):
    _insert_product()
    items = [{"id": PRODUCT_ID, "qty": 2, "price": 0.01}]
    shipping = quote_shipping(monkeypatch, settings, zip_code="33701", items=items)
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(shipping, items=items))

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    # 189.99 * 2 = 379.98, nunca el 0.01 * 2 que mandó el cliente.
    assert order.data["totals"]["subtotal"] == 379.98


@pytest.mark.django_db
def test_charges_the_current_price_even_when_the_cart_announced_an_older_one(monkeypatch, settings):
    # El `priceAtAdd` del carrito solo sirve para avisar; el cobro nunca lo usa.
    _insert_product()
    _insert_cart(
        "cart_price_changed",
        {"items": [{"id": PRODUCT_ID, "qty": 1, "priceAtAdd": 150.0}], "stage": "CART"},
    )
    items = [{"id": PRODUCT_ID, "qty": 1, "priceAtAdd": 150.0, "previousPrice": 150.0}]
    shipping = quote_shipping(monkeypatch, settings, zip_code="33701", items=items)
    sessions = []
    monkeypatch.setattr(
        CREATE_SESSION, lambda **kwargs: sessions.append(kwargs) or _fake_session()
    )

    response = _post(_body(shipping, items=items), guest_cart_client("cart_price_changed"))

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.data["totals"]["subtotal"] == 189.99
    assert "priceAtAdd" not in order.data["items"][0]
    assert float(Payment.objects.get(order=order).amount) == order.data["totals"]["total"]


@pytest.mark.django_db
def test_returns_409_when_fitment_check_fails(monkeypatch, shipping):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(shipping, vehicle={"make": "Ford", "year": 1996, "engine": "6.5"}))

    assert response.status_code == 409
    assert "VIN fitment check failed" in response.json()["error"]
    assert response.json()["field"] == "vehicle"
    assert not Order.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("overrides", [{"vehicle": None}, {"vehicle": {"vin": "  "}}])
def test_accepts_checkout_without_a_vin(overrides, monkeypatch, shipping):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())
    body = _body(shipping, **overrides)
    if body["vehicle"] is None:
        del body["vehicle"]

    response = _post(body)

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert not order.data["vehicle"].get("vin")


@pytest.mark.django_db
def test_returns_400_when_the_submitted_vin_is_malformed(monkeypatch, shipping):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(shipping, vehicle={**VEHICLE, "vin": "1GCHK3"}))

    assert response.status_code == 400
    assert response.json() == {"error": "VIN must contain 17 valid characters", "field": "vin"}
    assert not Order.objects.exists()


@pytest.mark.django_db
def test_stores_the_submitted_vin_normalized(monkeypatch, shipping):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(shipping, vehicle={**VEHICLE, "vin": " 1gchk33f6vf000001 "}))

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.data["vehicle"]["vin"] == "1GCHK33F6VF000001"


# --- shipping ------------------------------------------------------------


@pytest.mark.django_db
def test_charges_the_server_quoted_shipping_ignoring_the_client_amount(monkeypatch, shipping):
    _insert_product()
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return _fake_session()

    monkeypatch.setattr(CREATE_SESSION, _create)

    response = _post(_body({**shipping, "rate": 0.01}))

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.data["totals"]["shipping"] == SHIPPING_RATE
    assert order.data["shipping"]["rate"] == SHIPPING_RATE
    shipping_lines = [line for line in captured["line_items"] if line["name"] == "Shipping"]
    assert shipping_lines == [{"name": "Shipping", "unit_amount": 1250, "quantity": 1}]


@pytest.mark.django_db
@pytest.mark.parametrize("shipping_body", [None, {"rate": 0}, 25, {"shipmentId": "shp_checkout"}])
def test_returns_400_without_a_shipping_selection(shipping_body, monkeypatch):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(shipping_body))

    assert response.status_code == 400
    assert response.json() == {
        "error": "Select a shipping method before payment.",
        "field": "shipping",
    }
    assert not Order.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "selection, state, zip_code",
    [
        ({"shipmentId": "shp_checkout", "rateId": "rate_forged"}, "FL", "33701"),
        ({"shipmentId": "shp_other", "rateId": "rate_ground"}, "FL", "33701"),
        ({"shipmentId": "shp_checkout", "rateId": "rate_ground"}, "CA", "90210"),
    ],
)
def test_returns_409_when_the_shipping_rate_cannot_be_verified(
    selection, state, zip_code, monkeypatch, shipping
):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(selection, customer={"state": state, "zip": zip_code}))

    assert response.status_code == 409
    assert response.json()["error"] == (
        "Shipping rate could not be verified. Get shipping rates again."
    )
    assert not Order.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "items",
    [
        [{"id": PRODUCT_ID, "qty": 3}],
        [{"id": PRODUCT_ID, "qty": 1}, {"id": "heavy-block", "qty": 1}],
    ],
)
def test_returns_409_when_the_rate_was_quoted_for_other_items(items, monkeypatch, shipping):
    # La tarifa se cotizó para una sola unidad: no paga un carrito más pesado.
    _insert_product()
    _insert_product(product_id="heavy-block", data={**PRODUCT_DATA, "id": "heavy-block"})
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(shipping, items=items))

    assert response.status_code == 409
    assert response.json()["error"] == (
        "Shipping rate could not be verified. Get shipping rates again."
    )
    assert not Order.objects.exists()


@pytest.mark.django_db
def test_accepts_the_quoted_items_split_in_several_lines(monkeypatch, settings):
    _insert_product()
    shipping = quote_shipping(
        monkeypatch, settings, zip_code="33701", items=[{"id": PRODUCT_ID, "qty": 2}]
    )
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(
        _body(shipping, items=[{"id": PRODUCT_ID, "qty": 1}, {"id": PRODUCT_ID, "qty": 1}])
    )

    assert response.status_code == 200


# --- shipping address --------------------------------------------------------


def _forbid_stripe(monkeypatch):
    def _boom(**kwargs):
        raise AssertionError("Stripe must not be called for an invalid shipping address")

    monkeypatch.setattr(CREATE_SESSION, _boom)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("customer", "error", "field"),
    [
        ({"email": None}, "Valid email required", "email"),
        ({"email": "  "}, "Valid email required", "email"),
        ({"email": "not-an-email"}, "Valid email required", "email"),
        ({"email": "buyer@example"}, "Valid email required", "email"),
        ({"phone": "555-0100"}, "Phone must have 10 to 15 digits", "phone"),
        ({"phone": "+1 (941) 555-0100 ext 12345"}, "Phone must have 10 to 15 digits", "phone"),
        ({"phone": "call me"}, "Phone must have 10 to 15 digits", "phone"),
        ({"address1": None}, "Street address required", "address1"),
        ({"address1": "   "}, "Street address required", "address1"),
        ({"city": ""}, "City required", "city"),
        ({"city": 42}, "City required", "city"),
    ],
)
def test_returns_400_for_invalid_contact_fields(customer, error, field, monkeypatch, shipping):
    # Mismas reglas y mensajes que `src/lib/validators/checkout-customer.ts`.
    _insert_product()
    _forbid_stripe(monkeypatch)

    response = _post(_body(shipping, customer={"state": "FL", "zip": "33701", **customer}))

    assert response.status_code == 400
    assert response.json() == {"error": error, "field": field}
    assert not Order.objects.exists()


@pytest.mark.django_db
def test_contact_fields_are_trimmed_and_a_formatted_phone_is_accepted(monkeypatch, shipping):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())
    customer = {
        "email": " Buyer@Example.com ",
        "phone": "+1 (941) 555-0100",
        "address1": " 1 Main St ",
        "city": " Sarasota ",
        "state": "FL",
        "zip": "33701",
    }

    response = _post(_body(shipping, customer=customer))

    assert response.status_code == 200, response.content
    saved = Order.objects.get(pk=response.json()["orderId"]).data["customer"]
    assert (saved["email"], saved["address1"], saved["city"]) == (
        "Buyer@Example.com",
        "1 Main St",
        "Sarasota",
    )
    assert saved["phone"] == "+1 (941) 555-0100"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "customer",
    [
        {"zip": "33701"},
        {"state": "", "zip": "33701"},
        {"state": "   ", "zip": "33701"},
        {"state": None, "zip": "33701"},
    ],
)
def test_returns_400_when_the_shipping_state_is_missing(customer, monkeypatch, shipping):
    # Sin estado el impuesto daría 0 aunque el envío vaya a Florida.
    _insert_product()
    _forbid_stripe(monkeypatch)

    response = _post(_body(shipping, customer=customer))

    assert response.status_code == 400
    assert response.json() == {"error": "Shipping state is required", "field": "state"}
    assert not Order.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["ZZ", "Florida", "FLA", "AE", 12, ["FL"]])
def test_returns_400_when_the_shipping_state_is_not_a_us_state_we_ship_to(
    state, monkeypatch, shipping
):
    _insert_product()
    _forbid_stripe(monkeypatch)

    response = _post(_body(shipping, customer={"state": state, "zip": "33701"}))

    assert response.status_code == 400
    assert response.json() == {
        "error": "Shipping state must be a valid 2-letter US state code",
        "field": "state",
    }
    assert not Order.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("zip_code", [None, "", "3370", "ABCDE", 33701])
def test_returns_400_when_the_shipping_zip_is_missing_or_malformed(
    zip_code, monkeypatch, shipping
):
    _insert_product()
    _forbid_stripe(monkeypatch)

    response = _post(_body(shipping, customer={"state": "FL", "zip": zip_code}))

    assert response.status_code == 400
    assert response.json() == {"error": "Shipping ZIP must be 5 digits or ZIP+4", "field": "zip"}
    assert not Order.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("state", "zip_code"),
    [("GA", "33701"), ("GA", "33701-1234"), ("FL", "30301"), ("PR", "20001")],
)
def test_returns_400_when_the_zip_belongs_to_another_state(
    state, zip_code, monkeypatch, shipping
):
    # El paquete va al ZIP: un ZIP de Florida con estado "GA" esquivaría el
    # impuesto de FL.
    _insert_product()
    _forbid_stripe(monkeypatch)

    response = _post(_body(shipping, customer={"state": state, "zip": zip_code}))

    assert response.status_code == 400
    assert response.json() == {
        "error": "ZIP code does not match the selected state.",
        "field": "zip",
    }
    assert not Order.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("zip_code", ["00001", "21301", "34001"])
def test_returns_400_when_the_zip_prefix_is_not_a_us_zip_we_ship_to(
    zip_code, monkeypatch, shipping
):
    _insert_product()
    _forbid_stripe(monkeypatch)

    response = _post(_body(shipping, customer={"state": "FL", "zip": zip_code}))

    assert response.status_code == 400
    assert response.json() == {"error": "ZIP code is not a valid US ZIP code.", "field": "zip"}
    assert not Order.objects.exists()


@pytest.mark.django_db
def test_accepts_a_florida_zip_plus_four_with_florida(monkeypatch, settings):
    _insert_product()
    selection = quote_shipping(
        monkeypatch, settings, zip_code="33701-1234", items=[{"id": PRODUCT_ID, "qty": 1}]
    )
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(selection, customer={"state": "FL", "zip": "33701-1234"}))

    assert response.status_code == 200
    assert response.json()["tax"] == 15.15


@pytest.mark.django_db
def test_puerto_rico_zip_with_puerto_rico_is_accepted(monkeypatch, settings):
    _insert_product()
    selection = quote_shipping(
        monkeypatch, settings, zip_code="00901", items=[{"id": PRODUCT_ID, "qty": 1}]
    )
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(selection, customer={"state": "PR", "zip": "00901"}))

    assert response.status_code == 200
    assert response.json()["tax"] == 0


@pytest.mark.django_db
def test_the_shipping_state_is_normalized_before_tax_and_the_order(monkeypatch, shipping):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(shipping, customer={"state": " fl ", "zip": " 33701 "}))

    assert response.status_code == 200
    # 6 % de respaldo sobre 189.99 + 50 + 12.50: el estado en minúscula sigue
    # siendo Florida.
    assert response.json()["tax"] == 15.15
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.data["customer"]["state"] == "FL"
    assert order.data["customer"]["zip"] == "33701"


@pytest.mark.django_db
def test_district_of_columbia_is_a_valid_shipping_state(monkeypatch, settings):
    _insert_product()
    selection = quote_shipping(
        monkeypatch, settings, zip_code="20001", items=[{"id": PRODUCT_ID, "qty": 1}]
    )
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(selection, customer={"state": "DC", "zip": "20001"}))

    assert response.status_code == 200
    assert response.json()["tax"] == 0


# --- customer and tax ------------------------------------------------------


@pytest.mark.django_db
def test_guest_never_inherits_the_exemption_of_a_verified_guest_profile(monkeypatch, shipping):
    # Tipear el email de un invitado exento no prueba nada: se cobra el
    # impuesto y el perfil no se toca.
    _insert_product()
    _insert_customer(
        "cus_verified_1",
        "verified@example.com",
        tax_status="VERIFIED",
        data={"name": "Real Owner", "city": "Tampa"},
    )
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(
        _body(
            shipping,
            customer={
                "email": "verified@example.com",
                "name": "Mallory",
                "city": "Elsewhere",
                "state": "FL",
                "zip": "33701",
            },
        )
    )

    assert response.status_code == 200
    body = response.json()
    # FL fallback 0.06 sobre partes + core + envío.
    assert body["tax"] == round((239.99 + SHIPPING_RATE) * 0.06, 2)
    order = Order.objects.get(pk=body["orderId"])
    assert order.data["taxSource"] != "Tax exempt"
    assert order.data["customer"]["name"] == "Mallory"
    profile = Customer.objects.get(pk="cus_verified_1")
    assert profile.data == {"name": "Real Owner", "city": "Tampa"}
    assert profile.tax_status == "VERIFIED"


@pytest.mark.django_db
def test_non_verified_customer_gets_fallback_table_tax(monkeypatch, shipping):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(
        _body(shipping, customer={"email": "anon@example.com", "state": "FL", "zip": "33701"})
    )

    assert response.status_code == 200
    assert response.json()["tax"] == round((239.99 + SHIPPING_RATE) * 0.06, 2)


@pytest.mark.django_db
@pytest.mark.parametrize("state, zip_code", [("GA", "30301"), ("CA", "90001")])
def test_checkout_outside_florida_charges_no_tax(state, zip_code, monkeypatch, settings):
    _insert_product()
    selection = quote_shipping(
        monkeypatch, settings, zip_code=zip_code, rate=SHIPPING_RATE,
        items=[{"id": PRODUCT_ID, "qty": 1}],
    )
    settings.TAXJAR_API_KEY = "tj_test_fake"

    def _boom(**kwargs):
        raise AssertionError("TaxJar must not be called outside the nexus states")

    monkeypatch.setattr("apps.integrations.tax.taxjar.calculate_tax", _boom)
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(selection, customer={"state": state, "zip": zip_code}))

    assert response.status_code == 200
    assert response.json()["tax"] == 0
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.data["totals"]["tax"] == 0


@pytest.mark.django_db
def test_guest_order_attaches_to_existing_guest_profile_without_overwriting_it(
    monkeypatch, shipping
):
    _insert_product()
    _insert_customer("cus_existing_1", "repeat@example.com", data={"name": "Original"})
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(
        _body(
            shipping,
            customer={
                "email": "Repeat@Example.com",
                "name": "Repeat Customer",
                "state": "FL",
                "zip": "33701",
            },
        )
    )

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.customer_id == "cus_existing_1"
    assert order.data["customer"]["name"] == "Repeat Customer"
    assert Customer.objects.get(pk="cus_existing_1").data == {"name": "Original"}
    assert Customer.objects.count() == 1


@pytest.mark.django_db
def test_new_guest_email_creates_a_guest_profile_from_the_snapshot(monkeypatch, shipping):
    _insert_product()
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(
        _body(
            shipping,
            customer={"email": "new@example.com", "name": "New", "state": "FL", "zip": "33701"},
        )
    )

    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.customer.email == "new@example.com"
    assert order.customer.user_id is None
    assert order.customer.data["name"] == "New"


@pytest.mark.django_db
def test_guest_checkout_never_merges_into_a_registered_customer_profile(monkeypatch, shipping):
    # Un invitado solo escribe un email: si se mezclara con el perfil de una
    # cuenta registrada, cualquiera podría pisar su dirección o sumarle pedidos.
    from tests.factories import create_user

    _insert_product()
    owner = create_user("U_REGISTERED", email="owner@example.com")
    create_customer(
        "cus_registered", email="owner@example.com", user=owner, data={"city": "Tampa"}
    )
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(
        _body(
            shipping,
            customer={
                "email": "owner@example.com",
                "city": "Elsewhere",
                "state": "FL",
                "zip": "33701",
            },
        )
    )

    assert response.status_code == 200
    order = Order.objects.get(pk=response.json()["orderId"])
    assert order.customer_id != "cus_registered"
    assert Customer.objects.get(pk="cus_registered").data == {"city": "Tampa"}


# --- order, payment and cart ---------------------------------------------


@pytest.mark.django_db
def test_creates_order_and_pending_payment_via_stripe_sdk(monkeypatch, shipping):
    _insert_product()
    monkeypatch.setattr(
        CREATE_SESSION,
        lambda **kwargs: _fake_session(
            "cs_test_created", "https://checkout.stripe.com/pay/cs_test_created"
        ),
    )

    response = _post(_body(shipping))

    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "https://checkout.stripe.com/pay/cs_test_created"

    order = Order.objects.get(pk=body["orderId"])
    assert order.status == "PENDING_PAYMENT"
    assert order.payment_status == "UNPAID"

    payment = Payment.objects.get(order=order)
    assert payment.provider == "stripe"
    assert payment.provider_id == "cs_test_created"
    assert payment.status == "PENDING"
    assert float(payment.amount) == order.data["totals"]["total"]


@pytest.mark.django_db
def test_stripe_failure_cancels_the_order_and_leaves_the_cart_untouched(monkeypatch, shipping):
    _insert_product()
    _insert_cart("cart_fail_1", {"items": [{"id": PRODUCT_ID, "qty": 1}], "stage": "CART"})

    def _boom(**kwargs):
        raise ProviderError("Could not create secure checkout")

    monkeypatch.setattr(CREATE_SESSION, _boom)

    response = _post(_body(shipping), guest_cart_client("cart_fail_1"))

    assert response.status_code == 502
    order = Order.objects.get()
    # El número ya emitido queda en un pedido visible, no se reutiliza.
    assert order.status == "CANCELLED"
    assert order.status in OrderStatus.values
    assert order.payment_status == "UNPAID"
    assert order.data["cancelReason"] == "PAYMENT_SETUP_FAILED"
    assert not Payment.objects.filter(order=order).exists()
    cart = Cart.objects.get(pk="cart_fail_1").data
    assert cart["stage"] == "CART"
    assert "orderId" not in cart


@pytest.mark.django_db
def test_stripe_failure_returns_a_generic_message_and_logs_the_detail(
    monkeypatch, shipping, caplog
):
    _insert_product()

    def _boom(**kwargs):
        raise ProviderError("Invalid API Key for account acct_internal_123")

    monkeypatch.setattr(CREATE_SESSION, _boom)

    with caplog.at_level(logging.WARNING, logger="apps.checkout.services.storefront"):
        response = _post(_body(shipping), guest_cart_client("cart_fail_2"))

    assert response.status_code == 502
    assert response.json() == {"error": "Payment could not be started. Please try again."}
    assert "acct_internal_123" in caplog.text


@pytest.mark.django_db
def test_session_cart_transitions_to_checkout_stage(monkeypatch, shipping):
    _insert_product()
    _insert_cart("cart_uuid_checkout_1", {"items": [{"id": PRODUCT_ID, "qty": 1}], "stage": "CART"})
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(shipping), guest_cart_client("cart_uuid_checkout_1"))

    assert response.status_code == 200
    data = Cart.objects.get(pk="cart_uuid_checkout_1").data
    assert data["stage"] == "CHECKOUT"
    assert data["orderId"] == response.json()["orderId"]
    assert Order.objects.get().data["cartId"] == "cart_uuid_checkout_1"


@pytest.mark.django_db
def test_signed_in_checkout_links_the_account_cart(monkeypatch, shipping):
    # Con sesión el carrito es el de la cuenta (`Cart.user`), no uno de la sesión.
    from tests.factories import create_user, session_client

    _insert_product()
    user = create_user("U_CHECKOUT_CART")
    Cart.objects.create(
        id="cart_account",
        user=user,
        data={"items": [{"id": PRODUCT_ID, "qty": 1}], "stage": "CART"},
    )
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())
    client, _ = session_client("U_CHECKOUT_CART")

    response = _post(_body(shipping), client)

    assert response.status_code == 200
    data = Cart.objects.get(pk="cart_account").data
    assert data["stage"] == "CHECKOUT"
    assert data["orderId"] == response.json()["orderId"]
    assert Order.objects.get().data["cartId"] == "cart_account"


@pytest.mark.django_db
def test_body_cart_id_of_another_cart_is_ignored(monkeypatch, shipping):
    _insert_product()
    victim = {"items": [{"id": PRODUCT_ID, "qty": 1}], "stage": "CART"}
    _insert_cart("cart_victim", victim)
    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = _post(_body(shipping, cartId="cart_victim"))

    assert response.status_code == 200
    assert Cart.objects.get(pk="cart_victim").data == victim
    assert Order.objects.get().data["cartId"] is None
