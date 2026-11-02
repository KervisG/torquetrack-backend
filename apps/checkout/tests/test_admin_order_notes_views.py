"""`POST /api/admin/orders/<order_id>/notes/` (permiso `orders.status`).

Notas internas del pedido: dónde se pidió la pieza, verificaciones y
seguimiento. Solo las ve el panel; el portal del cliente nunca las devuelve.
Son de solo agregar: cada nota guarda quién la escribió y cuándo, y una nota
nueva no pisa las anteriores.
"""
import pytest
from django.utils import timezone

from apps.checkout.models import Order
from apps.customers.services import list_account_orders
from tests.factories import activity_count, create_customer, create_staff_user, session_client

STAFF_EMAIL = "seller@torquetrack.test"


def _staff(user_id="usr_notes", permissions=("orders.status",)):
    create_staff_user(user_id, permissions=list(permissions), email=STAFF_EMAIL)
    client, _ = session_client(user_id)
    return client


def _order(order_id="ord_note", number="O40001", data=None, **fields):
    now = timezone.now()
    return Order.objects.create(
        id=order_id,
        number=number,
        status="PROCESSING",
        payment_status="PAID",
        data=data if data is not None else {"customer": {"email": "buyer@example.com"}},
        created_at=now,
        updated_at=now,
        **fields,
    )


def _post(client, body, order_id="ord_note"):
    return client.post(f"/api/admin/orders/{order_id}/notes/", body, format="json")


# --- permisos -------------------------------------------------------------


@pytest.mark.django_db
def test_add_note_returns_403_without_orders_status():
    client = _staff(permissions=["orders.view"])
    _order()

    response = _post(client, {"body": "Ordered from supplier X"})

    assert response.status_code == 403
    assert "internalNotes" not in Order.objects.get(pk="ord_note").data


@pytest.mark.django_db
def test_add_note_returns_403_for_a_customer_session():
    from tests.factories import create_user

    create_user("usr_customer")
    client, _ = session_client("usr_customer")
    _order()

    response = _post(client, {"body": "Ordered from supplier X"})

    assert response.status_code == 403


@pytest.mark.django_db
def test_add_note_returns_404_for_an_unknown_order():
    client = _staff()

    response = _post(client, {"body": "Ordered from supplier X"}, order_id="missing")

    assert response.status_code == 404
    assert response.json() == {"error": "Order not found"}


# --- validación -----------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("body", [{}, {"body": ""}, {"body": "   "}, {"body": 42}])
def test_add_note_rejects_an_empty_or_invalid_body(body):
    client = _staff()
    _order()

    response = _post(client, body)

    assert response.status_code == 400
    assert response.json() == {"error": "Note is required"}


@pytest.mark.django_db
def test_add_note_rejects_a_body_over_the_limit():
    client = _staff()
    _order()

    response = _post(client, {"body": "x" * 2001})

    assert response.status_code == 400
    assert response.json() == {"error": "Note must be 2000 characters or fewer"}


# --- alta -----------------------------------------------------------------


@pytest.mark.django_db
def test_add_note_saves_author_and_date_and_logs_activity():
    client = _staff()
    _order()

    response = _post(client, {"body": "  Ordered from supplier X, PO 1234  "})

    assert response.status_code == 201
    note = response.json()["note"]
    assert note["body"] == "Ordered from supplier X, PO 1234"
    assert note["by"] == STAFF_EMAIL
    assert note["id"].startswith("note_")
    assert note["at"]
    assert Order.objects.get(pk="ord_note").data["internalNotes"] == [note]
    assert activity_count(action="ORDER_NOTE_ADDED", entity_id="ord_note") == 1


@pytest.mark.django_db
def test_add_note_appends_without_overwriting_previous_notes():
    client = _staff()
    _order()

    first = _post(client, {"body": "Ordered from supplier X"}).json()["note"]
    second = _post(client, {"body": "Supplier confirmed tracking"}).json()["note"]

    notes = Order.objects.get(pk="ord_note").data["internalNotes"]
    assert [n["id"] for n in notes] == [first["id"], second["id"]]


@pytest.mark.django_db
def test_admin_order_list_returns_internal_notes():
    client = _staff(permissions=["orders.status", "orders.view"])
    _order()
    note = _post(client, {"body": "Ordered from supplier X"}).json()["note"]

    orders = client.get("/api/admin/orders/").json()

    assert orders[0]["internalNotes"] == [note]


@pytest.mark.django_db
def test_customer_portal_never_returns_internal_notes():
    client = _staff()
    customer = create_customer("cus_notes", email="buyer@example.com")
    _order(customer=customer)
    _post(client, {"body": "Ordered from supplier X"})

    orders = list_account_orders(customer)

    assert "internalNotes" not in orders[0]
