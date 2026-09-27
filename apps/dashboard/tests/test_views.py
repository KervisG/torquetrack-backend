"""`GET /api/admin/dashboard/` con `dashboard.view`. Los contadores de carritos
salen de la misma clasificación que `GET /api/admin/carts/`."""

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone

from apps.cart.models import Cart
from apps.checkout.models import Order
from apps.quotes.models import Quote
from tests.factories import create_staff_user, session_client


def _admin_client(user_id, permissions):
    create_staff_user(user_id, permissions=permissions)
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


def _insert_cart(cart_id, updated_at, stage="CART", items=None):
    items = [{"id": "p1", "qty": 1}] if items is None else items
    Cart.objects.create(id=cart_id, data={"items": items, "stage": stage}, updated_at=updated_at)


def _insert_quote(quote_id, number, status, expires_at=None):
    Quote.objects.create(
        id=quote_id, number=number, status=status, data={}, expires_at=expires_at
    )


@pytest.mark.django_db
def test_dashboard_returns_403_without_permission():
    client = _admin_client("usr_dash_no_perm", [])

    response = client.get("/api/admin/dashboard/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_dashboard_returns_aggregate_counts():
    _insert_order("OID_1", "O10001", {"totals": {"total": 100.0}}, payment_status="PAID")
    _insert_order("OID_2", "O10002", {"totals": {"total": 50.0}}, payment_status="UNPAID")
    _insert_cart("cart_active", timezone.now())
    _insert_cart("cart_abandoned", timezone.now() - timezone.timedelta(minutes=45))
    _insert_quote("quo_active", "Q10001", "ACTIVE")
    _insert_quote("quo_building", "Q10002", "BUILDING")
    client = _admin_client("usr_dash", ["dashboard.view"])

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
def test_dashboard_cart_counts_match_the_carts_list():
    old = timezone.now() - timezone.timedelta(minutes=45)
    _insert_cart("cart_active", timezone.now())
    _insert_cart("cart_abandoned", old)
    _insert_cart("cart_checkout", old, stage="CHECKOUT")
    _insert_cart("cart_quote", timezone.now(), stage="BUILDING_QUOTE")
    _insert_cart("cart_empty", old, items=[])
    create_staff_user("usr_dash_carts", permissions=["dashboard.view", "carts.view"])
    client, _ = session_client("usr_dash_carts")

    counts = client.get("/api/admin/dashboard/").json()["counts"]
    statuses = [row["status"] for row in client.get("/api/admin/carts/").json()]

    assert counts["activeCarts"] == statuses.count("ACTIVE") == 1
    assert counts["abandonedCarts"] == statuses.count("ABANDONED") == 1


@pytest.mark.django_db
def test_dashboard_does_not_count_quotes_past_their_expiry_date():
    past = timezone.now() - timezone.timedelta(days=1)
    _insert_quote("quo_stale_active", "Q10001", "ACTIVE", expires_at=past)
    _insert_quote("quo_stale_building", "Q10002", "BUILDING", expires_at=past)
    future = timezone.now() + timezone.timedelta(days=1)
    _insert_quote("quo_live", "Q10003", "ACTIVE", expires_at=future)
    client = _admin_client("usr_dash_quotes", ["dashboard.view"])

    counts = client.get("/api/admin/dashboard/").json()["counts"]

    assert counts["activeQuotes"] == 1
    assert counts["buildingQuotes"] == 0


@pytest.mark.django_db
def test_dashboard_sales_today_sums_exact_cents_and_skips_other_days():
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
    client = _admin_client("usr_dash_sales", ["dashboard.view"])

    response = client.get("/api/admin/dashboard/")

    assert response.status_code == 200
    # La suma se hace como numeric: sin error de coma flotante.
    assert response.json()["counts"]["salesToday"] == 30.3


@pytest.mark.django_db
def test_dashboard_returns_zeros_on_an_empty_store():
    client = _admin_client("usr_dash_empty", ["dashboard.view"])

    response = client.get("/api/admin/dashboard/")

    assert response.json()["counts"] == {
        "orders": 0,
        "activeQuotes": 0,
        "buildingQuotes": 0,
        "activeCarts": 0,
        "abandonedCarts": 0,
        "salesToday": 0.0,
    }


@pytest.mark.django_db
def test_dashboard_view_permission_hangs_off_the_role_model():
    # `dashboard` no tiene modelos: el permiso vive en `authorization.role`.
    assert Permission.objects.filter(
        content_type__app_label="authorization",
        content_type__model="role",
        codename="view_dashboard",
    ).exists()
