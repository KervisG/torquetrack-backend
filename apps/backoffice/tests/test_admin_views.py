"""`GET /api/admin/dashboard` and `GET /api/admin/activity` (task 7.1),
pinned against `app/api/admin/dashboard/route.ts` and
`app/api/admin/activity/route.ts`.
"""

import pytest
from django.utils import timezone

from apps.backoffice.models import ActivityLog
from apps.cart.models import Cart
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


def _insert_order(order_id, number, data, payment_status="UNPAID", created_at=None):
    Order.objects.create(
        id=order_id,
        number=number,
        payment_status=payment_status,
        data=data,
        created_at=created_at or timezone.now(),
    )


def _insert_cart(cart_id, updated_at):
    Cart.objects.create(id=cart_id, data={}, updated_at=updated_at)


def _insert_quote(quote_id, number, status):
    Quote.objects.create(id=quote_id, number=number, status=status, data={})


# --- dashboard --------------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_returns_403_without_permission():
    _insert_user("usr_dash_no_perm", permissions=[])
    client = _admin_client("usr_dash_no_perm")

    response = client.get("/api/admin/dashboard/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_dashboard_returns_aggregate_counts():
    _insert_user("usr_dash", permissions=["dashboard.view"])
    _insert_order("OID_1", "O10001", {"totals": {"total": 100.0}}, payment_status="PAID")
    _insert_order("OID_2", "O10002", {"totals": {"total": 50.0}}, payment_status="UNPAID")
    _insert_cart("cart_active", timezone.now())
    _insert_cart("cart_abandoned", timezone.now() - timezone.timedelta(minutes=45))
    _insert_quote("quo_active", "Q10001", "ACTIVE")
    _insert_quote("quo_building", "Q10002", "BUILDING")

    client = _admin_client("usr_dash")
    response = client.get("/api/admin/dashboard/")

    assert response.status_code == 200
    counts = response.json()["counts"]
    assert counts["orders"] == 2
    assert counts["activeQuotes"] == 1
    assert counts["buildingQuotes"] == 1
    assert counts["activeCarts"] == 1
    assert counts["abandonedCarts"] == 1
    assert counts["salesToday"] == 100.0


@pytest.mark.django_db
def test_dashboard_sales_today_sums_exact_cents_and_skips_other_days():
    _insert_user("usr_dash_sales", permissions=["dashboard.view"])
    _insert_order("OID_A", "O10001", {"totals": {"total": 10.10}}, payment_status="PAID")
    _insert_order("OID_B", "O10002", {"totals": {"total": 20.20}}, payment_status="PAID")
    _insert_order("OID_C", "O10003", {"totals": {}}, payment_status="PAID")
    _insert_order(
        "OID_OLD",
        "O10004",
        {"totals": {"total": 999.0}},
        payment_status="PAID",
        created_at=timezone.now() - timezone.timedelta(days=2),
    )

    client = _admin_client("usr_dash_sales")
    response = client.get("/api/admin/dashboard/")

    assert response.status_code == 200
    # `sum(...::numeric)` del legado: sin error de coma flotante.
    assert response.json()["counts"]["salesToday"] == 30.3


@pytest.mark.django_db
def test_dashboard_returns_zeros_on_an_empty_store():
    _insert_user("usr_dash_empty", permissions=["dashboard.view"])

    client = _admin_client("usr_dash_empty")
    response = client.get("/api/admin/dashboard/")

    assert response.json()["counts"] == {
        "orders": 0,
        "activeQuotes": 0,
        "buildingQuotes": 0,
        "activeCarts": 0,
        "abandonedCarts": 0,
        "salesToday": 0.0,
    }


# --- activity -----------------------------------------------------------


@pytest.mark.django_db
def test_activity_returns_403_without_permission():
    _insert_user("usr_activity_no_perm", permissions=[])
    client = _admin_client("usr_activity_no_perm")

    response = client.get("/api/admin/activity/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_activity_returns_recent_logs_newest_first():
    _insert_user("usr_activity", permissions=["activity.view"])
    older = ActivityLog.objects.create(
        actor_id="usr_activity",
        action="USER_CREATED",
        entity_type="USER",
        entity_id="U1",
        data={},
        created_at=timezone.now() - timezone.timedelta(hours=1),
    )
    newer = ActivityLog.objects.create(
        actor_id="usr_activity",
        action="QUOTE_DELETED",
        entity_type="QUOTE",
        entity_id="Q1",
        data={"number": "Q10003"},
        created_at=timezone.now(),
    )

    client = _admin_client("usr_activity")
    response = client.get("/api/admin/activity/")

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body[:2]] == [newer.id, older.id]
    assert body[0]["action"] == "QUOTE_DELETED"
    assert body[0]["entity_id"] == "Q1"
