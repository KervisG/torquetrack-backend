"""`GET /api/admin/dashboard/` con `dashboard.view`. Los contadores de carritos
salen de la misma clasificación que `GET /api/admin/carts/`. Sin proveedores
que mockear.

`salesToday` son las ventas netas del día de la tienda
(`settings.STORE_TIME_ZONE`, Florida; no UTC): subtotal + core + envío de
los pedidos con un pago cobrado HOY (`Payment.paid_at`, no el `created_at` del
pedido), sin impuesto, menos los reembolsos `SUCCEEDED` emitidos hoy. El
borde del día se prueba fijando `django.utils.timezone.now` a las 23:30 ET.
"""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone

from apps.cart.models import Cart
from apps.checkout.models import Order, Payment, Refund
from apps.quotes.models import Quote
from tests.factories import create_staff_user, session_client


def _admin_client(user_id, permissions):
    create_staff_user(user_id, permissions=permissions)
    client, _ = session_client(user_id)
    return client


def _insert_order(order_id, number, data, payment_status="UNPAID", created_at=None):
    return Order.objects.create(
        id=order_id,
        number=number,
        payment_status=payment_status,
        data=data,
        created_at=created_at or timezone.now(),
    )


def _paid_order(order_id, totals, *, paid_at=None, created_at=None, status="PAID"):
    """Pedido con su `Payment` cobrado en `paid_at` (ahora por defecto)."""
    order = _insert_order(
        order_id, f"N-{order_id}", {"totals": totals}, payment_status=status,
        created_at=created_at,
    )
    payment = Payment.objects.create(
        id=f"PAY_{order_id}",
        order=order,
        provider="stripe",
        provider_id=f"cs_{order_id}",
        status=status,
        amount=Decimal(str(totals.get("total") or 0)),
        paid_at=paid_at or timezone.now(),
    )
    return order, payment


def _refund(refund_id, payment, amount, status="SUCCEEDED", created_at=None):
    Refund.objects.create(
        id=refund_id,
        payment=payment,
        amount=Decimal(amount),
        status=status,
        created_by="staff@example.com",
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
    _paid_order("OID_1", {"subtotal": 100.0, "total": 100.0})
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


def _sales_today():
    client = _admin_client("usr_dash_sales", ["dashboard.view"])
    response = client.get("/api/admin/dashboard/")
    assert response.status_code == 200
    return response.json()["counts"]["salesToday"]


@pytest.mark.django_db
def test_dashboard_sales_today_sums_exact_cents_without_tax():
    _paid_order("OID_A", {"subtotal": 10.10, "core": 0, "shipping": 0, "tax": 0.61, "total": 10.71})
    _paid_order("OID_B", {"subtotal": 15.00, "core": 5.00, "shipping": 0.20, "tax": 9.99})
    _paid_order("OID_C", {})

    # La suma se hace como numeric: sin error de coma flotante, y sin impuesto.
    assert _sales_today() == 30.3


@pytest.mark.django_db
def test_dashboard_sales_today_counts_by_payment_date_not_order_date():
    yesterday = timezone.now() - timezone.timedelta(days=1)
    _paid_order("OID_OLD_ORDER", {"subtotal": 40.0}, created_at=yesterday)
    _paid_order("OID_PAID_BEFORE", {"subtotal": 999.0}, paid_at=yesterday)

    assert _sales_today() == 40.0


@pytest.mark.django_db
def test_dashboard_sales_today_skips_orders_without_a_charged_payment():
    totals = {"subtotal": 70.0, "total": 70.0}
    _insert_order("OID_UNPAID", "O1", {"totals": totals}, payment_status="PAID")
    order = _insert_order("OID_PENDING", "O2", {"totals": {"subtotal": 80.0}})
    Payment.objects.create(
        id="PAY_PENDING", order=order, provider="stripe", status="PENDING", amount=Decimal("80")
    )

    assert _sales_today() == 0.0


@pytest.mark.django_db
def test_dashboard_sales_today_is_net_of_refunds_that_succeeded_today():
    _, payment = _paid_order("OID_R", {"subtotal": 100.0, "shipping": 10.0})
    _refund("REF_OK", payment, "25.50")
    _refund("REF_PENDING", payment, "10.00", status="PENDING")
    _refund("REF_FAILED", payment, "10.00", status="FAILED")

    assert _sales_today() == 84.5


@pytest.mark.django_db
def test_dashboard_sales_today_subtracts_today_refunds_of_older_payments():
    yesterday = timezone.now() - timezone.timedelta(days=1)
    _, old_payment = _paid_order(
        "OID_OLD", {"subtotal": 50.0}, paid_at=yesterday, status="PARTIALLY_REFUNDED"
    )
    _, payment = _paid_order("OID_NEW", {"subtotal": 30.0})
    _refund("REF_TODAY", old_payment, "20.00")
    _refund("REF_YESTERDAY", payment, "5.00", created_at=yesterday)

    assert _sales_today() == 10.0


@pytest.mark.django_db
def test_dashboard_sales_today_counts_refunded_payments_as_charged():
    _, payment = _paid_order("OID_FULL", {"subtotal": 60.0}, status="REFUNDED")
    _refund("REF_FULL", payment, "60.00")

    assert _sales_today() == 0.0


@pytest.mark.django_db
def test_dashboard_sales_today_is_the_florida_day_not_the_utc_day(monkeypatch):
    # 23:30 EDT del 5 de octubre = 03:30 UTC del 6: en Florida sigue siendo el 5.
    client = _admin_client("usr_dash_tz", ["dashboard.view"])
    now = datetime(2026, 10, 6, 3, 30, tzinfo=UTC)
    monkeypatch.setattr(timezone, "now", lambda: now)
    _paid_order("OID_LATE", {"subtotal": 10.0}, paid_at=now)
    _paid_order("OID_MORNING", {"subtotal": 20.0}, paid_at=datetime(2026, 10, 5, 5, tzinfo=UTC))
    # 23:00 EDT del 4 de octubre: ayer en Florida aunque en UTC ya sea el 5.
    _paid_order("OID_YESTERDAY", {"subtotal": 400.0}, paid_at=datetime(2026, 10, 5, 3, tzinfo=UTC))

    response = client.get("/api/admin/dashboard/")

    assert response.json()["counts"]["salesToday"] == 30.0


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
