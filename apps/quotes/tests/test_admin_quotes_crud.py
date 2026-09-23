
import pytest
from django.utils import timezone

from apps.quotes.models import Quote
from tests.factories import activity_count, create_staff_user, session_client


def _insert_user(user_id, permissions=None, active=True, full_access=False):
    create_staff_user(
        user_id, permissions=permissions, active=active, full_access=full_access
    )


def _admin_client(user_id):
    client, _ = session_client(user_id)
    return client


def _make_quote(quote_id="quo_crud_1", number="Q40001", status="ACTIVE", data=None, **kwargs):
    fields = {
        "id": quote_id,
        "number": number,
        "status": status,
        "data": data or {},
        "created_at": timezone.now(),
        "expires_at": timezone.now() + timezone.timedelta(days=30),
        "updated_at": timezone.now(),
        **kwargs,
    }
    return Quote.objects.create(**fields)


# --- list (GET) -----------------------------------------------------------


@pytest.mark.django_db
def test_list_returns_403_without_quotes_view_permission():
    _insert_user("usr_list_no_perm", permissions=[])
    client = _admin_client("usr_list_no_perm")

    response = client.get("/api/admin/quotes/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_list_expires_stale_quotes_and_excludes_archived():
    _insert_user("usr_list", permissions=["quotes.view"])
    _make_quote(
        quote_id="quo_stale",
        number="Q40002",
        status="ACTIVE",
        expires_at=timezone.now() - timezone.timedelta(days=1),
    )
    _make_quote(quote_id="quo_fresh", number="Q40003", status="ACTIVE")
    _make_quote(quote_id="quo_archived", number="Q40004", status="ACTIVE", data={"archived": True})

    client = _admin_client("usr_list")
    response = client.get("/api/admin/quotes/")

    assert response.status_code == 200
    body = response.json()
    numbers = {q["number"] for q in body}
    assert numbers == {"Q40002", "Q40003"}

    stale = Quote.objects.get(pk="quo_stale")
    assert stale.status == "EXPIRED"


# --- create/update (POST) --------------------------------------------------


@pytest.mark.django_db
def test_create_requires_quotes_create_permission():
    _insert_user("usr_create_no_perm", permissions=["quotes.view"])
    client = _admin_client("usr_create_no_perm")

    response = client.post("/api/admin/quotes/", {"items": []}, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_create_computes_totals_and_allocates_number():
    _insert_user("usr_create", permissions=["quotes.create"])
    client = _admin_client("usr_create")

    response = client.post(
        "/api/admin/quotes/",
        {
            "customer": {"name": "New Customer", "email": "new@example.com"},
            "items": [{"unitPrice": 100.0, "quantity": 2, "coreCharge": 10.0}],
            "shipping": 5,
            "tax": 6,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["updated"] is False
    totals = body["quote"]["totals"]
    assert totals["subtotal"] == 200.0
    assert totals["core"] == 20.0
    assert totals["total"] == 231.0

    quote = Quote.objects.get(pk=body["quote"]["id"])
    assert quote.number.startswith("Q")
    assert quote.status == "ACTIVE"
    assert quote.data["createdBy"] == "usr_create@example.com"


@pytest.mark.django_db
def test_update_existing_quote_preserves_number_and_dates():
    _insert_user("usr_update", permissions=["quotes.create"])
    quote = _make_quote(number="Q40005", status="BUILDING")
    original_created_at = quote.created_at
    original_expires_at = quote.expires_at

    client = _admin_client("usr_update")
    response = client.post(
        "/api/admin/quotes/",
        {"id": "quo_crud_1", "status": "ACTIVE", "items": []},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["updated"] is True
    assert body["quote"]["number"] == "Q40005"

    quote.refresh_from_db()
    assert quote.status == "ACTIVE"
    assert quote.created_at == original_created_at
    assert quote.expires_at == original_expires_at


@pytest.mark.django_db
def test_update_keeps_the_public_link_and_the_linked_order():
    """El editor manda la cotización completa, pero no conoce el token del
    enlace ya enviado ni el pedido vinculado: perderlos rompería el correo y
    el convert idempotente."""
    _insert_user("usr_update_keep", permissions=["quotes.create"])
    quote = _make_quote(
        number="Q40006",
        data={"publicToken": "tok-sent", "orderNumber": "O50001", "memo": "old"},
    )

    client = _admin_client("usr_update_keep")
    response = client.post(
        "/api/admin/quotes/",
        {"id": "quo_crud_1", "status": "CONTACTED", "items": [], "memo": "new"},
        format="json",
    )

    assert response.status_code == 200
    quote.refresh_from_db()
    assert quote.data["publicToken"] == "tok-sent"
    assert quote.data["orderNumber"] == "O50001"
    assert quote.data["memo"] == "new"


@pytest.mark.django_db
def test_update_returns_404_for_unknown_quote_id():
    _insert_user("usr_update2", permissions=["quotes.create"])
    client = _admin_client("usr_update2")

    response = client.post("/api/admin/quotes/", {"id": "does-not-exist"}, format="json")

    assert response.status_code == 404


# --- delete (DELETE) --------------------------------------------------------


@pytest.mark.django_db
def test_delete_requires_quotes_delete_permission():
    _insert_user("usr_delete_no_perm", permissions=["quotes.view"])
    _make_quote(quote_id="quo_del_1", number="Q40006")
    client = _admin_client("usr_delete_no_perm")

    response = client.delete("/api/admin/quotes/quo_del_1/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_delete_removes_quote_with_no_linked_order():
    _insert_user("usr_delete", permissions=["quotes.delete"])
    _make_quote(quote_id="quo_del_2", number="Q40007")
    client = _admin_client("usr_delete")

    response = client.delete("/api/admin/quotes/quo_del_2/")

    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "archived": False, "deletedQuote": "Q40007"}
    assert not Quote.objects.filter(pk="quo_del_2").exists()
    assert activity_count(action="QUOTE_DELETED", entity_id="quo_del_2") >= 1


@pytest.mark.django_db
def test_delete_archives_quote_linked_to_an_order_instead_of_deleting():
    _insert_user("usr_archive", permissions=["quotes.delete"])
    _make_quote(quote_id="quo_del_3", number="Q40008", data={"orderNumber": "O90001"})
    client = _admin_client("usr_archive")

    response = client.delete("/api/admin/quotes/quo_del_3/")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ok": True,
        "archived": True,
        "quoteNumber": "Q40008",
        "orderNumber": "O90001",
    }
    quote = Quote.objects.get(pk="quo_del_3")
    assert quote.data["archived"] is True
    assert quote.data["archivedBy"] == "usr_archive@example.com"
    assert activity_count(action="QUOTE_ARCHIVED", entity_id="quo_del_3") >= 1


@pytest.mark.django_db
def test_delete_returns_404_for_unknown_quote():
    _insert_user("usr_delete2", permissions=["quotes.delete"])
    client = _admin_client("usr_delete2")

    response = client.delete("/api/admin/quotes/does-not-exist/")

    assert response.status_code == 404
