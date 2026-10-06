"""Crear y editar una cotización desde el panel deja rastro en la bitácora
(`GET /api/admin/activity/`), además del `QUOTE_TAX_OVERRIDDEN` que ya se
registra al cambiar el impuesto a mano."""
import pytest
from django.utils import timezone

from apps.quotes.models import Quote
from tests.factories import activity_count, create_staff_user, session_client


@pytest.fixture(autouse=True)
def _no_taxjar(settings):
    settings.TAXJAR_API_KEY = ""


def _admin_client(user_id, permissions):
    create_staff_user(user_id, permissions=permissions)
    client, _ = session_client(user_id)
    return client


def _make_quote(quote_id, number, status="ACTIVE"):
    return Quote.objects.create(
        id=quote_id,
        number=number,
        status=status,
        data={},
        created_at=timezone.now(),
        expires_at=timezone.now() + timezone.timedelta(days=30),
        updated_at=timezone.now(),
    )


@pytest.mark.django_db
def test_post_create_records_quote_created_activity():
    client = _admin_client("usr_qact_new", ["quotes.create"])

    response = client.post(
        "/api/admin/quotes/",
        {
            "items": [{"unitPrice": 50.0, "quantity": 1}],
            "shippingAddress": {"state": "FL", "zip": "33701"},
        },
        format="json",
    )

    assert response.status_code == 200
    quote_id = response.json()["quote"]["id"]
    assert (
        activity_count(
            action="QUOTE_CREATED",
            entity_type="QUOTE",
            entity_id=quote_id,
            actor_id="usr_qact_new@example.com",
        )
        == 1
    )
    assert activity_count(action="QUOTE_TAX_OVERRIDDEN") == 0


@pytest.mark.django_db
def test_post_edit_records_quote_updated_activity():
    client = _admin_client("usr_qact_edit", ["quotes.create", "quotes.edit"])
    _make_quote("quo_qact_edit", "Q50001")

    response = client.post(
        "/api/admin/quotes/",
        {"id": "quo_qact_edit", "status": "CONTACTED", "items": []},
        format="json",
    )

    assert response.status_code == 200
    assert (
        activity_count(
            action="QUOTE_UPDATED",
            entity_type="QUOTE",
            entity_id="quo_qact_edit",
            actor_id="usr_qact_edit@example.com",
        )
        == 1
    )
    assert activity_count(action="QUOTE_CREATED", entity_id="quo_qact_edit") == 0


@pytest.mark.django_db
def test_rejected_post_records_no_activity():
    client = _admin_client("usr_qact_bad", ["quotes.create", "quotes.edit"])
    _make_quote("quo_qact_conv", "Q50002", status="CONVERTED")

    invalid = client.post(
        "/api/admin/quotes/", {"status": "NOPE", "items": []}, format="json"
    )
    missing = client.post("/api/admin/quotes/", {"id": "quo_missing"}, format="json")
    converted = client.post(
        "/api/admin/quotes/", {"id": "quo_qact_conv", "items": []}, format="json"
    )

    assert invalid.status_code == 400
    assert missing.status_code == 404
    assert converted.status_code == 409
    assert activity_count(entity_type="QUOTE") == 0
