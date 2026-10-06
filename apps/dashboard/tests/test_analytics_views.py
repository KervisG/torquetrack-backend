"""`GET /api/admin/dashboard/analytics/?range=7d|30d|90d|12m` con `dashboard.view`.

Sin proveedores que mockear: todo sale de la base. Reglas que se assertean a
propósito:

- El ingreso es el mismo de `salesToday`: subtotal + core + envío de los pagos
  cobrados (`Payment.paid_at`), sin impuesto, menos los `Refund` `SUCCEEDED`
  del día en que se emitieron. La serie suma lo mismo que el KPI.
- Los días (y meses con `12m`) se cortan en `settings.STORE_TIME_ZONE`
  (Florida, no UTC) y la serie viene completa con ceros; el último punto es
  hoy (o el mes en curso). El borde se prueba fijando
  `django.utils.timezone.now` a las 23:30 ET.
- Cada KPI trae el valor del período anterior de igual largo y el % de cambio
  (`null` si el anterior es 0).
- El dinero sale como número redondeado a centavos (`money`), igual que
  `salesToday`.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.cart.models import Cart
from apps.checkout.models import Order, Payment, Refund
from apps.common.business_day import store_today_bounds
from apps.quotes.models import Quote
from tests.factories import create_staff_user, session_client

URL = "/api/admin/dashboard/analytics/"


def _today_start():
    return store_today_bounds()[0]


def _days_ago(days, hour=12):
    """Mediodía de hace `days` días: lejos de los bordes del día."""
    return _today_start() - timedelta(days=days) + timedelta(hours=hour)


def _client(user_id="usr_analytics", permissions=("dashboard.view",)):
    create_staff_user(user_id, permissions=list(permissions))
    client, _ = session_client(user_id)
    return client


def _get(params=""):
    response = _client().get(f"{URL}{params}")
    assert response.status_code == 200, response.content
    return response.json()


def _order(order_id, *, totals=None, items=None, status="OPEN", payment_status="UNPAID",
           created_at=None, cart_id=None):
    data = {"totals": totals or {}, "items": items or []}
    if cart_id is not None:
        data["cartId"] = cart_id
    return Order.objects.create(
        id=order_id,
        number=f"N-{order_id}",
        status=status,
        payment_status=payment_status,
        data=data,
        created_at=created_at or timezone.now(),
    )


def _paid(order_id, totals, *, paid_at=None, items=None, status="PAID", **kwargs):
    order = _order(order_id, totals=totals, items=items, payment_status=status, **kwargs)
    payment = Payment.objects.create(
        id=f"PAY_{order_id}",
        order=order,
        provider="stripe",
        status=status,
        amount=Decimal(str(totals.get("total") or 0)),
        paid_at=paid_at or timezone.now(),
    )
    return order, payment


def _refund(refund_id, payment, amount, *, created_at=None, status="SUCCEEDED"):
    Refund.objects.create(
        id=refund_id,
        payment=payment,
        amount=Decimal(amount),
        status=status,
        created_by="staff@example.com",
        created_at=created_at or timezone.now(),
    )


# --- acceso y parámetros --------------------------------------------------------


@pytest.mark.django_db
def test_analytics_requires_dashboard_view():
    client = _client("usr_analytics_denied", permissions=())

    response = client.get(URL)

    assert response.status_code == 403
    assert "error" in response.json()


@pytest.mark.django_db
def test_analytics_rejects_an_unknown_range():
    response = _client().get(f"{URL}?range=1y")

    assert response.status_code == 400
    assert response.json() == {"error": "range must be one of 7d, 30d, 90d, 12m"}


@pytest.mark.django_db
def test_analytics_defaults_to_30_days_of_zero_filled_daily_points():
    body = _get()

    assert body["range"] == "30d"
    assert body["granularity"] == "day"
    series = body["revenueSeries"]
    assert len(series) == 30
    assert series[-1]["date"] == _today_start().date().isoformat()
    assert series[0]["date"] == (_today_start() - timedelta(days=29)).date().isoformat()
    assert all(point == {"date": point["date"], "revenue": 0.0, "orders": 0} for point in series)


@pytest.mark.django_db
@pytest.mark.parametrize(("range_key", "points"), [("7d", 7), ("30d", 30), ("90d", 90)])
def test_analytics_daily_ranges_have_one_point_per_day(range_key, points):
    body = _get(f"?range={range_key}")

    assert body["range"] == range_key
    assert len(body["revenueSeries"]) == points


@pytest.mark.django_db
def test_analytics_12m_has_one_point_per_month_ending_this_month():
    today = _today_start().date()

    body = _get("?range=12m")

    assert body["granularity"] == "month"
    series = body["revenueSeries"]
    assert len(series) == 12
    assert series[-1]["date"] == today.replace(day=1).isoformat()
    assert all(point["date"].endswith("-01") for point in series)


# --- ingresos -------------------------------------------------------------------


@pytest.mark.django_db
def test_revenue_series_buckets_net_sales_by_payment_day_without_tax():
    _paid("OID_T1", {"subtotal": 100.0, "shipping": 10.0, "tax": 7.0}, paid_at=_days_ago(0))
    _paid("OID_T2", {"subtotal": 50.0, "core": 5.0}, paid_at=_days_ago(0))
    _, payment = _paid("OID_D3", {"subtotal": 40.0}, paid_at=_days_ago(3))
    _refund("REF_1", payment, "15.00", created_at=_days_ago(1))
    _refund("REF_PENDING", payment, "5.00", created_at=_days_ago(1), status="PENDING")
    # Sin pago cobrado no es venta.
    _order("OID_UNPAID", totals={"subtotal": 999.0}, created_at=_days_ago(0))

    series = {point["date"]: point for point in _get("?range=7d")["revenueSeries"]}

    today = _today_start().date()
    assert series[today.isoformat()] == {"date": today.isoformat(), "revenue": 165.0, "orders": 2}
    assert series[(today - timedelta(days=3)).isoformat()]["revenue"] == 40.0
    assert series[(today - timedelta(days=3)).isoformat()]["orders"] == 1
    assert series[(today - timedelta(days=1)).isoformat()]["revenue"] == -15.0
    assert series[(today - timedelta(days=1)).isoformat()]["orders"] == 0


@pytest.mark.django_db
def test_today_revenue_point_matches_sales_today():
    _, payment = _paid("OID_TODAY", {"subtotal": 80.25, "shipping": 4.75}, paid_at=_days_ago(0))
    _refund("REF_TODAY", payment, "10.00", created_at=_days_ago(0))
    client = _client()

    analytics = client.get(URL).json()
    counts = client.get("/api/admin/dashboard/").json()["counts"]

    assert analytics["revenueSeries"][-1]["revenue"] == counts["salesToday"] == 75.0


@pytest.mark.django_db
def test_12m_series_sums_each_calendar_month():
    this_month = _today_start().replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    _paid("OID_M1", {"subtotal": 10.0}, paid_at=this_month + timedelta(hours=1))
    _paid("OID_M2", {"subtotal": 20.0}, paid_at=last_month + timedelta(days=2))
    _paid("OID_M3", {"subtotal": 30.0}, paid_at=last_month + timedelta(days=5))

    series = _get("?range=12m")["revenueSeries"]

    assert series[-1] == {"date": this_month.date().isoformat(), "revenue": 10.0, "orders": 1}
    assert series[-2] == {"date": last_month.date().isoformat(), "revenue": 50.0, "orders": 2}


@pytest.mark.django_db
def test_days_are_cut_in_the_store_time_zone_not_utc(monkeypatch):
    # 23:30 EDT del 5 de octubre = 03:30 UTC del 6: en Florida sigue siendo el 5.
    client = _client()
    now = datetime(2026, 10, 6, 3, 30, tzinfo=UTC)
    monkeypatch.setattr(timezone, "now", lambda: now)
    _paid("OID_LATE", {"subtotal": 10.0}, paid_at=now)
    # 23:00 EDT del 4 de octubre: ayer en Florida.
    _paid("OID_EVE", {"subtotal": 20.0}, paid_at=datetime(2026, 10, 5, 3, tzinfo=UTC))

    body = client.get(f"{URL}?range=7d").json()

    assert body["timeZone"] == "America/New_York"
    assert body["end"] == "2026-10-05"
    series = body["revenueSeries"]
    assert series[-1] == {"date": "2026-10-05", "revenue": 10.0, "orders": 1}
    assert series[-2] == {"date": "2026-10-04", "revenue": 20.0, "orders": 1}


# --- KPIs -----------------------------------------------------------------------


@pytest.mark.django_db
def test_kpis_compare_against_the_previous_period_of_equal_length():
    # Período actual (7d): dos pedidos, 100 + 50 cobrados, 30 reembolsados.
    _, current = _paid("OID_C1", {"subtotal": 100.0}, paid_at=_days_ago(1))
    _paid("OID_C2", {"subtotal": 50.0}, paid_at=_days_ago(6))
    _refund("REF_C", current, "30.00", created_at=_days_ago(0))
    # Período anterior (días 7 a 13): un pedido de 60, sin reembolsos.
    _paid("OID_P1", {"subtotal": 60.0}, paid_at=_days_ago(10))
    # Fuera de los dos períodos.
    _paid("OID_OLD", {"subtotal": 1000.0}, paid_at=_days_ago(20))

    kpis = _get("?range=7d")["kpis"]

    assert kpis["revenue"] == {"value": 120.0, "previous": 60.0, "changePercent": 100.0}
    assert kpis["orders"] == {"value": 2, "previous": 1, "changePercent": 100.0}
    # Ticket promedio sobre lo cobrado antes de reembolsos: 150 / 2.
    assert kpis["averageOrderValue"] == {"value": 75.0, "previous": 60.0, "changePercent": 25.0}
    assert kpis["refunds"] == {"value": 30.0, "previous": 0.0, "changePercent": None}


@pytest.mark.django_db
def test_kpis_are_zero_on_an_empty_store():
    kpis = _get()["kpis"]

    zero = {"value": 0.0, "previous": 0.0, "changePercent": None}
    assert kpis == {
        "revenue": zero,
        "orders": {"value": 0, "previous": 0, "changePercent": None},
        "averageOrderValue": zero,
        "refunds": zero,
    }


@pytest.mark.django_db
def test_revenue_series_adds_up_to_the_revenue_kpi():
    _, payment = _paid("OID_S1", {"subtotal": 33.33}, paid_at=_days_ago(2))
    _paid("OID_S2", {"subtotal": 66.67, "shipping": 1.0}, paid_at=_days_ago(5))
    _refund("REF_S", payment, "3.33", created_at=_days_ago(4))

    body = _get("?range=7d")

    total = sum(Decimal(str(point["revenue"])) for point in body["revenueSeries"])
    assert total == Decimal("97.67")
    assert body["kpis"]["revenue"]["value"] == 97.67


# --- pedidos por estado ------------------------------------------------------------


@pytest.mark.django_db
def test_orders_by_status_counts_orders_created_in_range_with_every_status():
    _order("OID_O1", status="OPEN", created_at=_days_ago(1))
    _order("OID_O2", status="OPEN", created_at=_days_ago(2))
    _order("OID_O3", status="CANCELLED", created_at=_days_ago(3))
    _order("OID_OLD", status="COMPLETED", created_at=_days_ago(40))

    rows = _get("?range=7d")["ordersByStatus"]

    assert rows == [
        {"status": "OPEN", "count": 2},
        {"status": "PENDING_PAYMENT", "count": 0},
        {"status": "PROCESSING", "count": 0},
        {"status": "COMPLETED", "count": 0},
        {"status": "CANCELLED", "count": 1},
        {"status": "REJECTED", "count": 0},
    ]


# --- productos más vendidos -------------------------------------------------------


@pytest.mark.django_db
def test_top_products_rank_by_revenue_across_charged_orders_in_range():
    pump = {"id": "pump", "title": "CP3 Pump", "partNumber": "0445020150", "price": 500.0}
    filter_item = {"id": "filter", "title": "Fuel Filter", "partNumber": "FF-1", "price": 20.0}
    _paid("OID_TP1", {"subtotal": 1040.0}, paid_at=_days_ago(1),
          items=[{**pump, "qty": 2, "coreCharge": 100.0}, {**filter_item, "qty": 2}])
    _paid("OID_TP2", {"subtotal": 60.0}, paid_at=_days_ago(2), items=[{**filter_item, "qty": 3}])
    # Línea de cotización convertida: `productId`, `quantity` y `unitPrice`.
    _paid("OID_TP3", {"subtotal": 300.0}, paid_at=_days_ago(3), items=[
        {"productId": "injector", "title": "Injector", "partNumber": "INJ-9",
         "quantity": 2, "unitPrice": 150.0}
    ])
    # Sin cobrar o fuera del período: no cuentan.
    _order("OID_TP_UNPAID", items=[{**pump, "qty": 9}], created_at=_days_ago(1))
    _paid("OID_TP_OLD", {"subtotal": 5000.0}, paid_at=_days_ago(60), items=[{**pump, "qty": 10}])

    rows = _get("?range=30d")["topProducts"]

    assert rows == [
        {"productId": "pump", "title": "CP3 Pump", "partNumber": "0445020150",
         "units": 2, "revenue": 1000.0},
        {"productId": "injector", "title": "Injector", "partNumber": "INJ-9",
         "units": 2, "revenue": 300.0},
        {"productId": "filter", "title": "Fuel Filter", "partNumber": "FF-1",
         "units": 5, "revenue": 100.0},
    ]


@pytest.mark.django_db
def test_top_products_returns_at_most_ten():
    items = [
        {"id": f"p{i}", "title": f"Part {i}", "partNumber": f"P{i}", "price": float(i), "qty": 1}
        for i in range(1, 13)
    ]
    _paid("OID_MANY", {"subtotal": 78.0}, paid_at=_days_ago(1), items=items)

    rows = _get()["topProducts"]

    assert len(rows) == 10
    assert [row["productId"] for row in rows[:2]] == ["p12", "p11"]


# --- embudo de cotizaciones ------------------------------------------------------


@pytest.mark.django_db
def test_quote_funnel_counts_quotes_created_in_range():
    Quote.objects.create(id="q1", number="Q1", status="BUILDING", data={}, created_at=_days_ago(1))
    Quote.objects.create(
        id="q2", number="Q2", status="CONTACTED", created_at=_days_ago(2),
        data={"lastEmailedAt": "2026-10-01T10:00:00+00:00"},
    )
    Quote.objects.create(
        id="q3", number="Q3", status="CONVERTED", created_at=_days_ago(3),
        data={"lastEmailedAt": "2026-10-01T10:00:00+00:00", "orderNumber": "O1"},
    )
    Quote.objects.create(id="q4", number="Q4", status="CONVERTED", data={}, created_at=_days_ago(4))
    Quote.objects.create(id="q_old", number="Q5", status="CONVERTED", data={},
                         created_at=_days_ago(50))

    funnel = _get()["quoteFunnel"]

    assert funnel == {"created": 4, "sent": 2, "converted": 2, "conversionRate": 50.0}


@pytest.mark.django_db
def test_quote_funnel_conversion_rate_is_zero_without_quotes():
    assert _get()["quoteFunnel"] == {"created": 0, "sent": 0, "converted": 0, "conversionRate": 0.0}


# --- embudo de carritos ----------------------------------------------------------


@pytest.mark.django_db
def test_cart_funnel_counts_created_checkout_converted_and_abandoned():
    items = [{"id": "p1", "qty": 1}]
    now = timezone.now()
    Cart.objects.create(id="c_active", data={"items": items, "stage": "CART"},
                        created_at=_days_ago(1), updated_at=now)
    Cart.objects.create(id="c_abandoned", data={"items": items, "stage": "CART"},
                        created_at=_days_ago(2), updated_at=_days_ago(2))
    Cart.objects.create(id="c_checkout", data={"items": items, "stage": "CHECKOUT"},
                        created_at=_days_ago(3), updated_at=_days_ago(3))
    Cart.objects.create(id="c_old", data={"items": items, "stage": "CART"},
                        created_at=_days_ago(80), updated_at=_days_ago(80))
    # Checkouts del storefront (con carrito) creados en el período.
    _order("OID_CK1", cart_id="c_checkout", status="PENDING_PAYMENT", created_at=_days_ago(3))
    _paid("OID_CK2", {"subtotal": 10.0}, cart_id="c_gone", paid_at=_days_ago(2),
          created_at=_days_ago(2))
    # Pedido sin carrito (del panel): no es un checkout del storefront.
    _order("OID_PANEL", created_at=_days_ago(2))

    funnel = _get()["cartFunnel"]

    assert funnel == {"created": 3, "checkoutStarted": 2, "converted": 1, "abandoned": 1}
