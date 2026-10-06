import base64

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.checkout.models import Order
from apps.customers.models import Customer
from apps.quotes.models import Quote
from tests.factories import create_customer, create_user, session_client


def _account(user_id="U_PAT", customer_id="C_PAT", data=None):
    user = create_user(user_id)
    create_customer(
        customer_id,
        email=user.email,
        user=user,
        data=data or {"name": "Pat Fleet", "company": "Fleet LLC"},
    )
    client, _ = session_client(user_id)
    return client


def _order(order_id, number, customer_id):
    now = timezone.now()
    return Order.objects.create(
        id=order_id,
        number=number,
        customer_id=customer_id,
        status="OPEN",
        payment_status="PAID",
        data={"items": [{"id": "p1"}], "totals": {"total": 10}, "internalNote": "x"},
        created_at=now,
        updated_at=now,
    )


def _quote(quote_id, number, customer_id):
    now = timezone.now()
    return Quote.objects.create(
        id=quote_id,
        number=number,
        customer_id=customer_id,
        status="SENT",
        data={"items": [], "totals": {"total": 5}},
        created_at=now,
        updated_at=now,
    )


def _pdf_data_url(size=16):
    payload = b"%PDF-1.4\n" + b"0" * size
    return "data:application/pdf;base64," + base64.b64encode(payload).decode()


# --- acceso ---------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    ["/api/account/", "/api/account/orders/", "/api/account/quotes/"],
)
def test_account_endpoints_return_401_without_session(path):
    assert APIClient().get(path).status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    ["/api/account/", "/api/account/orders/", "/api/account/quotes/"],
)
def test_account_endpoints_return_404_without_a_linked_customer(path):
    create_user("U_NO_PROFILE")
    client, _ = session_client("U_NO_PROFILE")

    response = client.get(path)

    assert response.status_code == 404
    assert response.json() == {"error": "Customer profile not found"}


# --- perfil ---------------------------------------------------------------------


@pytest.mark.django_db
def test_get_account_returns_the_whitelisted_profile():
    client = _account(data={"name": "Pat Fleet", "certificateData": "big", "taxId": "12-3456789"})

    response = client.get("/api/account/")

    assert response.status_code == 200
    customer = response.json()["customer"]
    assert customer["id"] == "C_PAT"
    assert customer["email"] == "u_pat@example.com"
    assert customer["name"] == "Pat Fleet"
    assert customer["taxStatus"] == "NOT SUBMITTED"
    assert "certificateData" not in customer
    assert "taxId" not in customer


@pytest.mark.django_db
def test_patch_account_updates_only_whitelisted_fields():
    client = _account()

    response = client.patch(
        "/api/account/",
        {
            "phone": "555-0199",
            "city": "Tampa",
            "taxStatus": "VERIFIED",
            "email": "evil@example.com",
            "tax_status": "VERIFIED",
            "certificateData": "forged",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["customer"]["phone"] == "555-0199"
    customer = Customer.objects.get(pk="C_PAT")
    assert customer.data["phone"] == "555-0199"
    assert customer.data["city"] == "Tampa"
    assert customer.data["name"] == "Pat Fleet"
    assert customer.tax_status == "NOT SUBMITTED"
    assert customer.email == "u_pat@example.com"
    assert "certificateData" not in customer.data
    assert "taxStatus" not in customer.data


@pytest.mark.django_db
def test_patch_account_rejects_non_string_values():
    client = _account()

    response = client.patch("/api/account/", {"phone": {"nested": True}}, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize(("raw", "saved"), [(" fl ", "FL"), ("dc", "DC"), ("", "")])
def test_patch_account_normalizes_the_state_code(raw, saved):
    # El estado del perfil precarga el checkout, que solo acepta un código válido.
    client = _account()

    response = client.patch("/api/account/", {"state": raw}, format="json")

    assert response.status_code == 200
    assert Customer.objects.get(pk="C_PAT").data["state"] == saved


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["Florida", "ZZ", "AE"])
def test_patch_account_rejects_a_state_we_do_not_ship_to(state):
    client = _account()

    response = client.patch("/api/account/", {"state": state, "city": "Tampa"}, format="json")

    assert response.status_code == 400
    assert response.json() == {
        "error": "State must be a valid 2-letter US state code",
        "field": "state",
    }
    assert "state" not in Customer.objects.get(pk="C_PAT").data
    assert "city" not in Customer.objects.get(pk="C_PAT").data


# --- pedidos y cotizaciones -------------------------------------------------------


@pytest.mark.django_db
def test_orders_returns_only_the_customers_own_orders():
    client = _account()
    create_customer("C_OTHER", email="other@example.com")
    _order("O_MINE", "TT-1", "C_PAT")
    _order("O_THEIRS", "TT-2", "C_OTHER")

    response = client.get("/api/account/orders/")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == ["O_MINE"]
    assert body[0]["number"] == "TT-1"
    assert body[0]["paymentStatus"] == "PAID"
    assert body[0]["totals"] == {"total": 10}
    assert "internalNote" not in body[0]


@pytest.mark.django_db
def test_orders_include_the_shipment_and_tracking_link():
    client = _account()
    order = _order("O_SHIPPED", "TT-3", "C_PAT")
    order.fulfillment_status = "SHIPPED"
    order.carrier = "FEDEX"
    order.tracking_number = "123456789012"
    order.shipped_at = timezone.now()
    order.save()
    _order("O_NEW", "TT-4", "C_PAT")

    body = {row["id"]: row for row in client.get("/api/account/orders/").json()}

    shipped = body["O_SHIPPED"]
    assert shipped["fulfillmentStatus"] == "SHIPPED"
    assert shipped["carrier"] == "FEDEX"
    assert shipped["trackingNumber"] == "123456789012"
    assert shipped["trackingUrl"] == "https://www.fedex.com/fedextrack/?trknbr=123456789012"
    assert shipped["shippedAt"]
    assert shipped["deliveredAt"] is None
    assert body["O_NEW"]["fulfillmentStatus"] == "UNFULFILLED"
    assert body["O_NEW"]["trackingUrl"] is None


@pytest.mark.django_db
def test_quotes_returns_only_the_customers_own_quotes():
    client = _account()
    create_customer("C_OTHER", email="other@example.com")
    _quote("Q_MINE", "Q-1", "C_PAT")
    _quote("Q_THEIRS", "Q-2", "C_OTHER")

    response = client.get("/api/account/quotes/")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["Q_MINE"]


# --- exención fiscal ----------------------------------------------------------------


def _tax_payload(**overrides):
    payload = {
        "company": "Fleet LLC",
        "taxId": "12-3456789",
        "taxState": "fl",
        "taxExemptionType": "Resale",
        "certificateName": "cert.pdf",
        "certificateData": _pdf_data_url(),
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_tax_exemption_returns_401_without_session():
    response = APIClient().post("/api/account/tax-exemption/", _tax_payload(), format="json")

    assert response.status_code == 401


@pytest.mark.django_db
def test_tax_exemption_stores_submission_and_sets_pending_verification():
    client = _account()

    response = client.post("/api/account/tax-exemption/", _tax_payload(), format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "PENDING VERIFICATION"
    customer = Customer.objects.get(pk="C_PAT")
    assert customer.tax_status == "PENDING VERIFICATION"
    assert customer.data["taxCompany"] == "Fleet LLC"
    assert customer.data["taxId"] == "12-3456789"
    assert customer.data["taxState"] == "FL"
    assert customer.data["certificateName"] == "cert.pdf"
    assert customer.data["certificateData"].startswith("data:application/pdf;base64,")
    assert customer.data["taxReviewedAt"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("missing", ["taxId", "company", "taxState"])
def test_tax_exemption_requires_tax_id_company_and_state(missing):
    client = _account()

    response = client.post(
        "/api/account/tax-exemption/", _tax_payload(**{missing: ""}), format="json"
    )

    assert response.status_code == 400
    assert Customer.objects.get(pk="C_PAT").tax_status == "NOT SUBMITTED"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "certificate",
    [
        "data:text/html;base64," + base64.b64encode(b"<script>").decode(),
        "data:application/pdf;base64,***not-base64***",
        "plain text",
    ],
)
def test_tax_exemption_rejects_unsupported_certificate_types(certificate):
    client = _account()

    response = client.post(
        "/api/account/tax-exemption/",
        _tax_payload(certificateData=certificate),
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_tax_exemption_rejects_an_oversized_certificate(monkeypatch):
    from apps.customers.services import storefront

    monkeypatch.setattr(storefront, "MAX_CERTIFICATE_BYTES", 32)
    client = _account()

    response = client.post(
        "/api/account/tax-exemption/",
        _tax_payload(certificateData=_pdf_data_url(size=64)),
        format="json",
    )

    assert response.status_code == 413


@pytest.mark.django_db
def test_tax_exemption_accepts_a_submission_without_certificate():
    client = _account()

    response = client.post(
        "/api/account/tax-exemption/",
        _tax_payload(certificateData="", certificateName=""),
        format="json",
    )

    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(("state", "zip_code"), [("GA", "33701"), ("FL", "30301-1234")])
def test_patch_account_rejects_a_zip_from_another_state(state, zip_code):
    # El perfil precarga el checkout, que rechaza el mismo par.
    client = _account()

    response = client.patch("/api/account/", {"state": state, "zip": zip_code}, format="json")

    assert response.status_code == 400
    assert response.json() == {
        "error": "ZIP code does not match the selected state.",
        "field": "zip",
    }
    assert "zip" not in Customer.objects.get(pk="C_PAT").data


@pytest.mark.django_db
def test_patch_account_accepts_a_matching_state_and_zip():
    client = _account()

    response = client.patch("/api/account/", {"state": "fl", "zip": "33701-1234"}, format="json")

    assert response.status_code == 200
    data = Customer.objects.get(pk="C_PAT").data
    assert (data["state"], data["zip"]) == ("FL", "33701-1234")
