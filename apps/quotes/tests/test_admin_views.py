
import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.checkout.models import Order
from apps.quotes.models import Quote
from apps.quotes.services.admin import convert_quote_to_order
from apps.quotes.tests.pdf_support import requires_weasyprint
from tests.factories import activity_count, create_staff_user, session_client
from tests.fakes import FakeResend, install_resend


def _insert_user(user_id, permissions=None, active=True, full_access=False):
    create_staff_user(
        user_id, permissions=permissions, active=active, full_access=full_access
    )


def _admin_client(user_id):
    client, _ = session_client(user_id)
    return client


def _make_quote(
    quote_id="quo_admin_1", number="Q30001", status="ACTIVE", data=None, expires_at=None
):
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
        expires_at=expires_at or timezone.now() + timezone.timedelta(days=30),
        updated_at=timezone.now(),
    )


# --- 403/404 compartidos (por la ruta de convert) --------------------


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
    assert activity_count(action="QUOTE_CONVERTED", entity_id="quo_admin_1") >= 1


@pytest.mark.django_db
def test_convert_rejects_a_quote_past_its_expiry_date():
    _insert_user("usr_convert_past", permissions=["quotes.convert"])
    _make_quote(expires_at=timezone.now() - timezone.timedelta(days=1))

    response = _admin_client("usr_convert_past").post("/api/admin/quotes/quo_admin_1/convert/")

    assert response.status_code == 400
    assert not Order.objects.exists()


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
def test_preview_generates_public_token_when_missing(settings):
    settings.APP_URL = "https://shop.example.test"
    _insert_user("usr_preview", permissions=["quotes.view"])
    _make_quote()
    client = _admin_client("usr_preview")

    response = client.post("/api/admin/quotes/quo_admin_1/preview/")

    assert response.status_code == 200
    url = response.json()["url"]
    quote = Quote.objects.get(pk="quo_admin_1")
    token = quote.data["publicToken"]
    assert token
    # El enlace abre la página del SPA, no el endpoint HTML de la API.
    assert url == f"https://shop.example.test/quote/{token}"


@pytest.mark.django_db
def test_preview_reuses_existing_public_token(settings):
    settings.APP_URL = "https://shop.example.test/"
    _insert_user("usr_preview2", permissions=["quotes.view"])
    _make_quote(data={"publicToken": "already-issued-token"})
    client = _admin_client("usr_preview2")

    response = client.post("/api/admin/quotes/quo_admin_1/preview/")

    assert response.status_code == 200
    assert response.json()["url"] == "https://shop.example.test/quote/already-issued-token"


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
@requires_weasyprint
def test_send_emails_quote_with_pdf_attachment_and_logs_activity(settings, monkeypatch):
    settings.RESEND_API_KEY = "re_test_fake"
    settings.FROM_EMAIL = "sales@torquetrackdiesel.com"
    _insert_user("usr_send2", permissions=["quotes.send"])
    _make_quote(status="BUILDING")

    resend = install_resend(monkeypatch, FakeResend({"sent": True, "id": "email_123"}))

    client = _admin_client("usr_send2")
    response = client.post("/api/admin/quotes/quo_admin_1/send/")

    assert response.status_code == 200
    body = response.json()
    assert body["emailId"] == "email_123"

    assert resend.sent[0]["to"] == ["pat@example.com"]
    assert len(resend.sent[0]["attachments"]) == 1
    assert resend.sent[0]["attachments"][0]["contentType"] == "application/pdf"

    quote = Quote.objects.get(pk="quo_admin_1")
    assert quote.status == "CONTACTED"
    assert quote.data["publicToken"]
    assert quote.data["lastEmailedTo"] == "pat@example.com"
    assert activity_count(action="QUOTE_EMAILED", entity_id="quo_admin_1") >= 1


@pytest.mark.django_db
@requires_weasyprint
def test_send_returns_502_when_email_provider_not_configured(settings):
    settings.RESEND_API_KEY = ""
    settings.FROM_EMAIL = ""
    _insert_user("usr_send3", permissions=["quotes.send"])
    _make_quote()
    client = _admin_client("usr_send3")

    response = client.post("/api/admin/quotes/quo_admin_1/send/")

    assert response.status_code == 502


@pytest.mark.django_db
def test_send_links_the_spa_quote_page_and_the_api_pdf(settings, monkeypatch):
    """El correo apunta a `/quote/<token>` del SPA; la descarga del PDF sigue
    en la API porque el SPA no sirve archivos."""
    settings.APP_URL = "https://shop.example.test"
    settings.RESEND_API_KEY = "re_test_fake"
    settings.FROM_EMAIL = "sales@torquetrackdiesel.com"
    _insert_user("usr_send_links", permissions=["quotes.send"])
    _make_quote(data={"publicToken": "tok-links"})

    resend = install_resend(monkeypatch, FakeResend({"sent": True, "id": "email_links"}))
    monkeypatch.setattr("apps.quotes.services.admin.render_quote_pdf_base64", lambda quote: "UERG")

    client = _admin_client("usr_send_links")
    response = client.post("/api/admin/quotes/quo_admin_1/send/")

    assert response.status_code == 200
    assert response.json()["url"] == "https://shop.example.test/quote/tok-links"
    html = resend.sent[0]["html"]
    assert 'href="https://shop.example.test/quote/tok-links"' in html
    assert 'href="https://shop.example.test/api/quote/public/tok-links/pdf/"' in html
    # Los clientes de correo bloquean el SVG: el correo lleva el PNG publicado.
    assert '<img src="https://shop.example.test/brand/email-logo.png"' in html
    assert "<svg" not in html


@pytest.mark.django_db
def test_send_reports_unconfigured_email_before_rendering_the_pdf(settings, monkeypatch):
    """Sin Resend el envío falla igual: se responde 502 antes de generar el
    PDF, así el panel muestra el motivo aunque WeasyPrint no esté instalado."""
    settings.RESEND_API_KEY = ""
    settings.FROM_EMAIL = ""
    _insert_user("usr_send_unconfigured", permissions=["quotes.send"])
    _make_quote()

    def _no_pdf(quote):
        raise AssertionError("the PDF must not be rendered when email is not configured")

    monkeypatch.setattr("apps.quotes.services.admin.render_quote_pdf_base64", _no_pdf)

    client = _admin_client("usr_send_unconfigured")
    response = client.post("/api/admin/quotes/quo_admin_1/send/")

    assert response.status_code == 502
    assert response.json() == {"error": "Email provider not configured"}


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["LOST", "BUILDING", "CONVERTED"])
def test_convert_rejects_a_quote_that_is_not_convertible(status):
    # CONVERTED sin pedido vinculado: el pedido lo creó (y lo pudo borrar)
    # otro camino; convertir de nuevo abriría un segundo cobro.
    _insert_user("usr_convert_closed", permissions=["quotes.convert"])
    _make_quote(status=status)

    response = _admin_client("usr_convert_closed").post("/api/admin/quotes/quo_admin_1/convert/")

    assert response.status_code == 409
    assert response.json() == {"error": "This quote cannot be converted in its current status."}
    assert not Order.objects.exists()


@pytest.mark.django_db
def test_convert_rejects_an_archived_quote():
    _insert_user("usr_convert_archived", permissions=["quotes.convert"])
    _make_quote(data={"archived": True})

    response = _admin_client("usr_convert_archived").post(
        "/api/admin/quotes/quo_admin_1/convert/"
    )

    assert response.status_code == 409
    assert not Order.objects.exists()


@pytest.mark.django_db
def test_double_conversion_leaves_a_single_order():
    """Dos requests que leyeron la cotización antes de que cualquiera la
    convirtiera: la segunda relee la fila bloqueada y reusa el pedido."""
    _make_quote()
    first_read = Quote.objects.get(pk="quo_admin_1")
    second_read = Quote.objects.get(pk="quo_admin_1")

    first = convert_quote_to_order(first_read, "staff@example.com")
    second = convert_quote_to_order(second_read, "staff@example.com")

    assert Order.objects.count() == 1
    assert second["existing"] is True
    assert second["order"]["number"] == first["order"]["number"]
    assert activity_count(action="QUOTE_CONVERTED", entity_id="quo_admin_1") == 1


@pytest.mark.django_db
def test_send_escapes_customer_data_in_the_email(settings, monkeypatch):
    # El correo sale de la plantilla de Django: el autoescape es la defensa.
    settings.RESEND_API_KEY = "re_test_fake"
    settings.FROM_EMAIL = "sales@torquetrackdiesel.com"
    _insert_user("usr_send_escape", permissions=["quotes.send"])
    _make_quote(
        data={
            "customer": {
                "name": "<script>alert(1)</script>",
                "company": "<b>Acme</b>",
                "email": "pat@example.com",
            },
            "notes": "<b>rush</b>",
        }
    )
    resend = install_resend(monkeypatch)
    monkeypatch.setattr("apps.quotes.services.admin.render_quote_pdf_base64", lambda quote: "UERG")

    response = _admin_client("usr_send_escape").post("/api/admin/quotes/quo_admin_1/send/")

    assert response.status_code == 200
    html = resend.sent[0]["html"]
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<b>Acme</b>" not in html
    assert "&lt;b&gt;Acme&lt;/b&gt;" in html
