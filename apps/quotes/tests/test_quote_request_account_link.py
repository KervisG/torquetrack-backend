"""`POST /api/quote/request/` con una sesión de cliente.

Una cuenta con `Customer` vinculado pide la cotización como ese perfil (sin
resolver el cliente por el email del body), con el email de la cuenta, y
el perfil no se reescribe con el nombre o teléfono del body. El pedido
invitado sigue cubierto en `test_public_views.py`.

Resend queda sin configurar (`RESEND_API_KEY = ""`): ningún correo sale.
"""

import pytest

from apps.catalog.models import Product
from apps.customers.models import Customer
from apps.quotes.models import Quote
from tests.factories import create_customer, create_user, session_client

PRODUCT_ID = "cummins-5.9-turbo-holset-hx35"
PROFILE = {"name": "Pat Fleet", "phone": "555-0000"}


@pytest.fixture(autouse=True)
def _setup(settings):
    settings.RESEND_API_KEY = ""
    settings.SALES_EMAIL = ""
    Product.objects.create(
        id=PRODUCT_ID,
        data={"id": PRODUCT_ID, "title": "HX35", "partNumber": "HX35-590", "price": 429.0},
        active=True,
    )


def _account():
    user = create_user("U_PAT", email="pat@example.com")
    create_customer("C_PAT", email="pat@example.com", user=user, data=dict(PROFILE))
    client, _ = session_client("U_PAT")
    return client


def _request(client, customer):
    return client.post(
        "/api/quote/request/",
        {"customer": customer, "items": [{"productId": PRODUCT_ID, "quantity": 1}]},
        format="json",
    )


@pytest.mark.django_db
def test_signed_in_quote_request_attaches_to_linked_profile():
    create_customer("C_GUEST", email="other@example.com")
    client = _account()

    response = _request(
        client, {"name": "Mallory", "email": "other@example.com", "phone": "555-9999"}
    )

    assert response.status_code == 200
    quote = Quote.objects.get(pk=response.json()["quoteId"])
    assert quote.customer_id == "C_PAT"
    assert quote.data["customer"]["email"] == "pat@example.com"
    assert Customer.objects.get(pk="C_PAT").data == PROFILE
    assert Customer.objects.get(pk="C_GUEST").data == {}


@pytest.mark.django_db
def test_signed_in_quote_request_uses_profile_name_when_body_has_none():
    client = _account()

    response = _request(client, {})

    assert response.status_code == 200
    quote = Quote.objects.get(pk=response.json()["quoteId"])
    assert quote.customer_id == "C_PAT"
    assert quote.data["customer"]["name"] == "Pat Fleet"
