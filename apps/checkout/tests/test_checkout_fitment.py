"""`POST /api/checkout/`: el chequeo de fitment del `vehicle` usa las filas de
`ProductFitment` cuando el producto las tiene y el texto de `data` cuando no.

Stripe se parchea en `apps.integrations.payments.stripe.create_checkout_session`
y la tarifa de envío con `quote_shipping` de `tests/fakes.py`."""
import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Application, Product
from apps.checkout.models import Order
from tests.fakes import quote_shipping

CREATE_SESSION = "apps.integrations.payments.stripe.create_checkout_session"
PRODUCT_ID = "ford-73-injector"
# El texto dice 1994-2003 7.3; las filas lo acotan a la aplicación 1994-1997.
PRODUCT_DATA = {"id": PRODUCT_ID, "title": "7.3L Injector", "partNumber": "AP63992",
                "price": 189.99, "make": "Ford", "yearFrom": 1994, "yearTo": 2003,
                "engine": "7.3"}
FORD_73_EARLY = {"id": "ford-73-powerstroke-1994-1997", "make": "Ford", "yearFrom": 1994,
                 "yearTo": 1997, "engine": "7.3", "models": ["F-250"]}


@pytest.fixture(autouse=True)
def _keys(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = "sk_test_fake_not_real"
    settings.TAXJAR_API_KEY = ""
    monkeypatch.setattr(
        CREATE_SESSION, lambda **kwargs: {"id": "cs_test_1", "url": "https://stripe.test/cs"}
    )


@pytest.fixture
def shipping(monkeypatch, settings):
    return quote_shipping(
        monkeypatch, settings, zip_code="33701", rate=10, items=[{"id": PRODUCT_ID, "qty": 1}]
    )


def _insert_product(linked):
    product = Product.objects.create(id=PRODUCT_ID, data=PRODUCT_DATA)
    if linked:
        product.applications.set([Application.objects.create(data=FORD_73_EARLY)])


def _post(shipping, vehicle):
    return APIClient().post(
        "/api/checkout/",
        {"items": [{"id": PRODUCT_ID, "qty": 1}], "vehicle": vehicle,
         "customer": {"email": "ada@example.com", "address1": "1 Main St", "city": "Tampa",
                      "state": "FL", "zip": "33701"}, "shipping": shipping},
        format="json",
    )


@pytest.mark.django_db
def test_vehicle_outside_the_fitment_rows_is_rejected(shipping):
    _insert_product(linked=True)

    response = _post(shipping, {"make": "Ford", "year": 1999, "engine": "7.3"})

    assert response.status_code == 409
    assert response.json() == {
        "error": "VIN fitment check failed: AP63992: "
        "vehicle 1999 Ford 7.3 is not a listed application for this product",
        "field": "vehicle",
    }
    assert not Order.objects.exists()


@pytest.mark.django_db
def test_vehicle_inside_the_fitment_rows_passes(shipping):
    _insert_product(linked=True)

    response = _post(shipping, {"make": "Ford", "year": 1996, "engine": "7.3"})

    assert response.status_code == 200, response.json()
    assert Order.objects.count() == 1


@pytest.mark.django_db
def test_product_without_fitment_rows_keeps_the_text_check(shipping):
    _insert_product(linked=False)

    # 1999 cae dentro del texto 1994-2003: sin filas el pedido pasa.
    response = _post(shipping, {"make": "Ford", "year": 1999, "engine": "7.3"})

    assert response.status_code == 200, response.json()
