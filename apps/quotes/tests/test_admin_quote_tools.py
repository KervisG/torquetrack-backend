"""`POST /api/admin/quotes/vin/` y `/tax/` para el editor, y el impuesto que
guarda `POST /api/admin/quotes/`. El VIN inválido no llama a NHTSA; el
impuesto sin TaxJar usa la tabla de respaldo (sin key de TaxJar, así que no se
mockea el adaptador).

La exención sale siempre del `Customer` de la cotización (`quoteId`,
`customerId` o el email de una cuenta registrada), nunca del perfil del
empleado en sesión: el staff también puede tener su propio perfil exento.
"""
import pytest
from django.utils import timezone

from apps.quotes.models import Quote
from tests.factories import create_customer, create_staff_user, create_user, session_client

_FL_BODY = {"subtotal": 100, "coreCharge": 0, "shipping": 0, "state": "FL", "zip": ""}


@pytest.fixture(autouse=True)
def _no_taxjar(settings):
    settings.TAXJAR_API_KEY = ""


def _exempt_staff(user_id="usr_tax_exempt_staff"):
    """Empleado con permiso de cotizar y un perfil propio con exención verificada."""
    staff = create_staff_user(user_id, permissions=["quotes.create", "quotes.edit"])
    create_customer(f"C_{user_id}", email=staff.email, user=staff, tax_status="VERIFIED")
    client, _ = session_client(user_id)
    return client


def _plain_staff(user_id="usr_tax_plain_staff"):
    create_staff_user(user_id, permissions=["quotes.create", "quotes.edit"])
    client, _ = session_client(user_id)
    return client


def _registered_customer(customer_id, email, tax_status):
    user = create_user(f"usr_{customer_id}", email=email)
    return create_customer(customer_id, email=email, user=user, tax_status=tax_status)


@pytest.mark.django_db
def test_vin_decode_requires_quotes_create_and_rejects_a_short_vin():
    create_staff_user("usr_vin_no", permissions=["quotes.view"])
    denied, _ = session_client("usr_vin_no")
    assert denied.post("/api/admin/quotes/vin/", {"vin": "1"}, format="json").status_code == 403

    create_staff_user("usr_vin", permissions=["quotes.create"])
    client, _ = session_client("usr_vin")
    response = client.post("/api/admin/quotes/vin/", {"vin": "SHORT"}, format="json")

    assert response.status_code == 400
    assert "17" in response.json()["error"]


@pytest.mark.django_db
def test_tax_estimate_uses_the_state_fallback():
    create_staff_user("usr_tax", permissions=["quotes.create"])
    client, _ = session_client("usr_tax")

    response = client.post(
        "/api/admin/quotes/tax/",
        {"subtotal": 100, "coreCharge": 0, "shipping": 0, "state": "FL", "zip": ""},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["tax"] == 6


@pytest.mark.django_db
def test_tax_estimate_exempts_a_verified_customer_even_if_the_staff_is_not():
    customer = _registered_customer("C_tax_exempt", "exempt@example.com", "VERIFIED")
    client = _plain_staff()

    response = client.post(
        "/api/admin/quotes/tax/", {**_FL_BODY, "customerId": customer.pk}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["tax"] == 0
    assert response.json()["exempt"] is True


@pytest.mark.django_db
def test_tax_estimate_charges_a_non_exempt_customer_even_if_the_staff_is_exempt():
    customer = _registered_customer("C_tax_plain", "plain@example.com", "NOT SUBMITTED")
    client = _exempt_staff()

    response = client.post(
        "/api/admin/quotes/tax/", {**_FL_BODY, "customerId": customer.pk}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["tax"] == 6


@pytest.mark.django_db
def test_tax_estimate_without_customer_ignores_the_staff_exemption():
    client = _exempt_staff()

    response = client.post("/api/admin/quotes/tax/", _FL_BODY, format="json")

    assert response.status_code == 200
    assert response.json()["tax"] == 6


@pytest.mark.django_db
def test_tax_estimate_uses_the_customer_saved_on_the_quote():
    customer = _registered_customer("C_tax_quote", "quoted@example.com", "VERIFIED")
    now = timezone.now()
    quote = Quote.objects.create(
        id="QID_tax", number="Q70001", customer=customer, status="ACTIVE",
        data={}, created_at=now, expires_at=now, updated_at=now,
    )
    client = _plain_staff()

    # El `customerId` del body no pisa al cliente ya guardado en la cotización.
    other = _registered_customer("C_tax_other", "other@example.com", "NOT SUBMITTED")
    response = client.post(
        "/api/admin/quotes/tax/",
        {**_FL_BODY, "quoteId": quote.pk, "customerId": other.pk},
        format="json",
    )

    assert response.json()["tax"] == 0


@pytest.mark.django_db
def test_tax_estimate_finds_a_registered_customer_by_email_when_there_is_no_id():
    _registered_customer("C_tax_mail", "Mail@Example.com", "VERIFIED")
    client = _plain_staff()

    response = client.post(
        "/api/admin/quotes/tax/", {**_FL_BODY, "email": "mail@example.com"}, format="json"
    )

    assert response.json()["tax"] == 0


@pytest.mark.django_db
def test_tax_estimate_never_exempts_a_guest_profile_found_by_email():
    create_customer("C_tax_guest", email="guest@example.com", tax_status="VERIFIED")
    client = _plain_staff()

    response = client.post(
        "/api/admin/quotes/tax/", {**_FL_BODY, "email": "guest@example.com"}, format="json"
    )

    assert response.json()["tax"] == 6


def _quote_body(**extra):
    return {
        "customer": {"name": "Fleet Co", "email": ""},
        "items": [{"unitPrice": 100.0, "quantity": 1, "coreCharge": 0}],
        "shipping": 0,
        # El servidor recalcula el impuesto con esta dirección (6 % de la
        # tabla de respaldo de FL, sin key de TaxJar); el `tax` del body se ignora.
        "shippingAddress": {"state": "FL", "zip": "33701"},
        "tax": 6,
        **extra,
    }


@pytest.mark.django_db
def test_saving_a_quote_for_an_exempt_customer_stores_zero_tax():
    customer = _registered_customer("C_save_exempt", "save-exempt@example.com", "VERIFIED")
    client = _plain_staff()

    response = client.post(
        "/api/admin/quotes/", _quote_body(customerId=customer.pk), format="json"
    )

    assert response.status_code == 200
    totals = response.json()["quote"]["totals"]
    assert totals["tax"] == 0
    assert totals["total"] == 100
    quote = Quote.objects.get(pk=response.json()["quote"]["id"])
    assert quote.data["totals"]["tax"] == 0
    assert quote.data["taxExempt"] is True


@pytest.mark.django_db
def test_saving_a_quote_keeps_the_tax_for_a_non_exempt_customer_of_an_exempt_staff():
    customer = _registered_customer("C_save_plain", "save-plain@example.com", "NOT SUBMITTED")
    client = _exempt_staff()

    response = client.post(
        "/api/admin/quotes/", _quote_body(customerId=customer.pk), format="json"
    )

    assert response.status_code == 200
    assert response.json()["quote"]["totals"]["tax"] == 6
    quote = Quote.objects.get(pk=response.json()["quote"]["id"])
    assert quote.data["taxExempt"] is False


@pytest.mark.django_db
def test_the_body_cannot_mark_a_quote_tax_exempt():
    client = _plain_staff()

    response = client.post(
        "/api/admin/quotes/", _quote_body(taxExempt=True, exempt=True), format="json"
    )

    quote = Quote.objects.get(pk=response.json()["quote"]["id"])
    assert quote.data["taxExempt"] is False
    assert "exempt" not in quote.data
    assert quote.data["totals"]["tax"] == 6


@pytest.mark.django_db
def test_converting_a_quote_of_an_exempt_customer_keeps_zero_tax_on_the_order():
    from apps.checkout.models import Order

    customer = _registered_customer("C_conv_exempt", "conv-exempt@example.com", "VERIFIED")
    create_staff_user("usr_tax_convert", permissions=["quotes.create", "quotes.convert"])
    client, _ = session_client("usr_tax_convert")
    saved = client.post(
        "/api/admin/quotes/", _quote_body(customerId=customer.pk), format="json"
    ).json()["quote"]

    response = client.post(f"/api/admin/quotes/{saved['id']}/convert/")

    assert response.status_code == 200
    order = Order.objects.get(number=response.json()["order"]["number"])
    assert order.customer_id == customer.pk
    assert order.data["totals"]["tax"] == 0
