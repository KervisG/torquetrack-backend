"""Admin quote actions (task 6.3): convert/preview/reopen/send, pinned
against `app/api/admin/quotes/[id]/{convert,preview,reopen,send}/route.ts`.

RBAC-gated via `SessionUserAuthentication` + `HasTorqueTrackPermission`.
Los tests recorren el camino real cookie -> sesión -> `request.user` con
una sesión creada en `SessionStore` y enviada como cookie de sesión (`SESSION_COOKIE_NAME`).
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.backoffice.models import ActivityLog
from apps.checkout.models import Order
from apps.quotes.models import Quote
from tests.factories import create_staff_user, session_client


def _insert_user(user_id, permissions=None, active=True, full_access=False):
    create_staff_user(
        user_id, permissions=permissions, active=active, full_access=full_access
    )


def _admin_client(user_id):
    client, _ = session_client(user_id)
    return client


def _make_quote(quote_id="quo_admin_1", number="Q30001", status="ACTIVE", data=None):
    return Quote.objects.create(
        id=quote_id,
        number=number,
        status=status,
        data={
            "customer": {"name": "Pat Diesel", "email": "pat@example.com"},
            "items": [{"title": "Part", "partNumber": "P-1", "quantity": 1, "unitPrice": 100.0}],
            "totals": {"subtotal": 100.0, "core": 0, "shipping": 0, "tax": 0, "total": 100.0},
            **(data or {}),
        },
        created_at=timezone.now(),
        expires_at=timezone.now() + timezone.timedelta(days=30),
        updated_at=timezone.now(),
    )


# --- shared 403/404 behavior (via the convert route) --------------------


@pytest.mark.django_db
def test_admin_action_returns_403_without_session():
    _make_quote()

    response = APIClient().post("/api/admin/quotes/quo_admin_1/convert/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_action_returns_403_without_the_required_permission():
    _insert_user("usr_no_perm", permissions=["quotes.view"])
    _make_quote()
    client = _admin_client("usr_no_perm")

    response = client.post("/api/admin/quotes/quo_admin_1/convert/")

    assert response.status_code == 403


# --- convert --------------------------------------------------------------


@pytest.mark.django_db
def test_convert_creates_order_from_quote():
    _insert_user("usr_convert", permissions=["quotes.convert"])
    _make_quote()
    client = _admin_client("usr_convert")

    response = client.post("/api/admin/quotes/quo_admin_1/convert/")

    assert response.status_code == 200
    body = response.json()
    order = Order.objects.get(number=body["order"]["number"])
    assert order.status == "OPEN"
    assert order.data["quoteNumber"] == "Q30001"

    quote = Quote.objects.get(pk="quo_admin_1")
    assert quote.status == "CONVERTED"
    assert ActivityLog.objects.filter(action="QUOTE_CONVERTED", entity_id="quo_admin_1").exists()


@pytest.mark.django_db
def test_convert_rejects_expired_status_quote():
    _insert_user("usr_convert2", full_access=True)
    _make_quote(quote_id="quo_admin_expired", number="Q30002", status="EXPIRED")
    client = _admin_client("usr_convert2")

    response = client.post("/api/admin/quotes/quo_admin_expired/convert/")

    assert response.status_code == 400
    assert response.json()["error"] == "Reopen this quote before converting it."


@pytest.mark.django_db
def test_convert_reuses_existing_order_when_already_converted():
    _insert_user("usr_convert3", full_access=True)
    Order.objects.create(
        id="OID_PRIOR",
        number="O80001",
        status="OPEN",
        payment_status="UNPAID",
        data={},
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )
    _make_quote(
        quote_id="quo_admin_converted",
        number="Q30003",
        status="CONVERTED",
        data={"orderNumber": "O80001"},
    )
    client = _admin_client("usr_convert3")

    response = client.post("/api/admin/quotes/quo_admin_converted/convert/")

    assert response.status_code == 200
    body = response.json()
    assert body["existing"] is True
    assert body["order"]["number"] == "O80001"
    assert Order.objects.filter(number="O80001").count() == 1


@pytest.mark.django_db
def test_convert_returns_404_for_unknown_quote():
    _insert_user("usr_convert4", full_access=True)
    client = _admin_client("usr_convert4")

    response = client.post("/api/admin/quotes/does-not-exist/convert/")

    assert response.status_code == 404


# --- preview (generate/reuse public link) ----------------------------------


@pytest.mark.django_db
def test_preview_generates_public_token_when_missing():
    _insert_user("usr_preview", permissions=["quotes.view"])
    _make_quote()
    client = _admin_client("usr_preview")

    response = client.post("/api/admin/quotes/quo_admin_1/preview/")

    assert response.status_code == 200
    url = response.json()["url"]
    quote = Quote.objects.get(pk="quo_admin_1")
    token = quote.data["publicToken"]
    assert token
    assert url.endswith(f"/api/quote/public/{token}")


@pytest.mark.django_db
def test_preview_reuses_existing_public_token():
    _insert_user("usr_preview2", permissions=["quotes.view"])
    _make_quote(data={"publicToken": "already-issued-token"})
    client = _admin_client("usr_preview2")

    response = client.post("/api/admin/quotes/quo_admin_1/preview/")

    assert response.status_code == 200
    assert response.json()["url"].endswith("/api/quote/public/already-issued-token")


# --- reopen -----------------------------------------------------------------


@pytest.mark.django_db
def test_reopen_resets_status_and_expiry():
    _insert_user("usr_reopen", permissions=["quotes.edit"])
    _make_quote(status="EXPIRED")

    client = _admin_client("usr_reopen")
    response = client.post("/api/admin/quotes/quo_admin_1/reopen/")

    assert response.status_code == 200
    quote = Quote.objects.get(pk="quo_admin_1")
    assert quote.status == "ACTIVE"
    assert quote.expires_at > timezone.now()


# --- send ---------------------------------------------------------------


@pytest.mark.django_db
def test_send_requires_customer_email():
    _insert_user("usr_send", permissions=["quotes.send"])
    _make_quote(data={"customer": {"name": "No Email"}})
    client = _admin_client("usr_send")

    response = client.post("/api/admin/quotes/quo_admin_1/send/")

    assert response.status_code == 400
    assert response.json()["error"] == "Customer email is required"


@pytest.mark.django_db
def test_send_emails_quote_with_pdf_attachment_and_logs_activity(settings, monkeypatch):
    settings.RESEND_API_KEY = "re_test_fake"
    settings.FROM_EMAIL = "sales@torquetrackdiesel.com"
    _insert_user("usr_send2", permissions=["quotes.send"])
    _make_quote(status="BUILDING")

    captured = {}

    class _FakeResponse:
        ok = True

        def json(self):
            return {"id": "email_123"}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse()

    monkeypatch.setattr("apps.quotes.services.requests.post", _fake_post)

    client = _admin_client("usr_send2")
    response = client.post("/api/admin/quotes/quo_admin_1/send/")

    assert response.status_code == 200
    body = response.json()
    assert body["emailId"] == "email_123"

    assert captured["payload"]["to"] == ["pat@example.com"]
    assert len(captured["payload"]["attachments"]) == 1
    assert captured["payload"]["attachments"][0]["content_type"] == "application/pdf"

    quote = Quote.objects.get(pk="quo_admin_1")
    assert quote.status == "CONTACTED"
    assert quote.data["publicToken"]
    assert quote.data["lastEmailedTo"] == "pat@example.com"
    assert ActivityLog.objects.filter(action="QUOTE_EMAILED", entity_id="quo_admin_1").exists()


@pytest.mark.django_db
def test_send_returns_502_when_email_provider_not_configured(settings):
    settings.RESEND_API_KEY = ""
    settings.FROM_EMAIL = ""
    _insert_user("usr_send3", permissions=["quotes.send"])
    _make_quote()
    client = _admin_client("usr_send3")

    response = client.post("/api/admin/quotes/quo_admin_1/send/")

    assert response.status_code == 502
