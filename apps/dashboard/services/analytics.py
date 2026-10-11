"""Analítica del dashboard (`GET /api/admin/dashboard/analytics/`): solo lee.

El ingreso es el mismo de `salesToday` (`net_sales_between` en `counts.py`):
subtotal + core + envío de los pagos cobrados por `Payment.paid_at`, sin
impuesto, menos los `Refund` `SUCCEEDED` por `Refund.created_at`. Los días y
los meses se cortan en `settings.STORE_TIME_ZONE` (`apps/common/business_day.py`),
la misma zona de "hoy" en `salesToday`, así el último punto de la serie
coincide con esa tarjeta.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, F, Max, Q, Sum, TextField, Value
from django.db.models.functions import Coalesce, NullIf, Trunc
from django.utils import timezone

from apps.cart.services import count_abandoned_carts_between, count_carts_created_between
from apps.checkout.models import Order, OrderItem, OrderStatus, Payment, Refund, RefundStatus
from apps.checkout.services import CHARGED_PAYMENT_STATUSES
from apps.common.business_day import store_timezone, store_today
from apps.common.numbers import ZERO, money, money_decimal
from apps.dashboard.services.counts import net_of_tax
from apps.quotes.models import Quote, QuoteStatus

DAILY_RANGES = {"7d": 7, "30d": 30, "90d": 90}
MONTHLY_RANGE = "12m"
MONTHLY_RANGE_MONTHS = 12
ANALYTICS_RANGES = (*DAILY_RANGES, MONTHLY_RANGE)
DEFAULT_ANALYTICS_RANGE = "30d"
INVALID_RANGE = f"range must be one of {', '.join(ANALYTICS_RANGES)}"
TOP_PRODUCTS_LIMIT = 10

_ONE_DECIMAL = Decimal("0.1")


@dataclass(frozen=True)
class _Window:
    """Período [start, end) y el anterior de igual largo, con sus cubetas."""

    kind: str
    buckets: list[date]
    start: datetime
    end: datetime
    previous_start: datetime


def _add_months(day: date, months: int) -> date:
    """Primer día del mes que queda `months` meses después de `day`."""
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _window(range_key: str, now: datetime) -> _Window:
    tz = store_timezone()
    today = store_today(now)
    if range_key == MONTHLY_RANGE:
        first = _add_months(today.replace(day=1), -(MONTHLY_RANGE_MONTHS - 1))
        buckets = [_add_months(first, offset) for offset in range(MONTHLY_RANGE_MONTHS)]
        end = _add_months(first, MONTHLY_RANGE_MONTHS)
        previous = _add_months(first, -MONTHLY_RANGE_MONTHS)
        kind = "month"
    else:
        days = DAILY_RANGES[range_key]
        first = today - timedelta(days=days - 1)
        buckets = [first + timedelta(days=offset) for offset in range(days)]
        end = today + timedelta(days=1)
        previous = first - timedelta(days=days)
        kind = "day"

    def midnight(day: date) -> datetime:
        return datetime.combine(day, time.min, tz)

    return _Window(kind, buckets, midnight(first), midnight(end), midnight(previous))


def _charged_payments(start, end):
    # Un pago sin pedido no tiene totales que sumar (igual que en `counts.py`).
    return Payment.objects.filter(
        order__isnull=False,
        status__in=CHARGED_PAYMENT_STATUSES,
        paid_at__gte=start,
        paid_at__lt=end,
    )


def _succeeded_refunds(start, end):
    return Refund.objects.filter(
        status=RefundStatus.SUCCEEDED, created_at__gte=start, created_at__lt=end
    )


def _sales_totals(start, end) -> tuple[Decimal, Decimal, int]:
    """(cobrado sin impuesto, reembolsado, pedidos con un cobro) en [start, end)."""
    charged = _charged_payments(start, end).aggregate(
        gross=Sum(net_of_tax("order__"), default=ZERO),
        orders=Count("order", distinct=True),
    )
    refunded = _succeeded_refunds(start, end).aggregate(total=Sum("amount", default=ZERO))
    return charged["gross"], refunded["total"], charged["orders"]


def _bucketed(queryset, field: str, window: _Window, **aggregates) -> dict:
    tz = store_timezone()
    rows = (
        queryset.annotate(bucket=Trunc(field, window.kind, tzinfo=tz))
        .values("bucket")
        .annotate(**aggregates)
        .order_by()
    )
    return {timezone.localtime(row.pop("bucket"), tz).date(): row for row in rows}


def _revenue_series(window: _Window) -> list[dict]:
    charged = _bucketed(
        _charged_payments(window.start, window.end),
        "paid_at",
        window,
        gross=Sum(net_of_tax("order__")),
        orders=Count("order", distinct=True),
    )
    refunded = _bucketed(
        _succeeded_refunds(window.start, window.end), "created_at", window, total=Sum("amount")
    )
    series = []
    for bucket in window.buckets:
        sales = charged.get(bucket, {})
        refunds = (refunded.get(bucket) or {}).get("total") or ZERO
        series.append(
            {
                "date": bucket.isoformat(),
                "revenue": money((sales.get("gross") or ZERO) - refunds),
                "orders": sales.get("orders") or 0,
            }
        )
    return series


def _change_percent(value, previous) -> float | None:
    if not previous:
        return None
    change = (Decimal(value) - Decimal(previous)) / Decimal(previous) * 100
    return float(change.quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP))


def _kpi(value, previous, *, is_money: bool = True) -> dict:
    shape = money if is_money else int
    return {
        "value": shape(value),
        "previous": shape(previous),
        "changePercent": _change_percent(value, previous),
    }


def _average(gross: Decimal, orders: int) -> Decimal:
    # Ticket promedio sobre lo cobrado, antes de reembolsos.
    return money_decimal(gross / orders) if orders else ZERO


def _kpis(window: _Window) -> dict:
    gross, refunds, orders = _sales_totals(window.start, window.end)
    prev_gross, prev_refunds, prev_orders = _sales_totals(window.previous_start, window.start)
    return {
        "revenue": _kpi(money_decimal(gross - refunds), money_decimal(prev_gross - prev_refunds)),
        "orders": _kpi(orders, prev_orders, is_money=False),
        "averageOrderValue": _kpi(_average(gross, orders), _average(prev_gross, prev_orders)),
        "refunds": _kpi(money_decimal(refunds), money_decimal(prev_refunds)),
    }


def _orders_by_status(window: _Window) -> list[dict]:
    counts = dict(
        Order.objects.filter(created_at__gte=window.start, created_at__lt=window.end)
        .values_list("status")
        .annotate(count=Count("pk"))
        .order_by()
    )
    return [{"status": status, "count": counts.get(status, 0)} for status in OrderStatus.values]


def _top_products(window: _Window) -> list[dict]:
    """Por lo vendido (precio x cantidad, sin core ni envío) en los pedidos con
    un cobro en el período, agrupado por producto. Una línea personalizada,
    sin producto, se agrupa por número de parte o, sin él, por título."""
    order_ids = _charged_payments(window.start, window.end).values("order_id")
    rows = (
        OrderItem.objects.filter(order_id__in=order_ids)
        .annotate(
            key=Coalesce(
                "product_id",
                NullIf("part_number", Value("")),
                NullIf("title", Value("")),
                output_field=TextField(),
            )
        )
        .exclude(key=None)
        .values("key")
        .annotate(
            product=Max("product_id"),
            title=Max("title"),
            part_number=Max("part_number"),
            units=Sum("quantity"),
            revenue=Sum(F("unit_price") * F("quantity")),
        )
        .order_by("-revenue", "-units", "title")[:TOP_PRODUCTS_LIMIT]
    )
    return [
        {
            "productId": row["product"],
            "title": row["title"],
            "partNumber": row["part_number"],
            "units": row["units"],
            "revenue": money(row["revenue"]),
        }
        for row in rows
    ]


def _quote_funnel(window: _Window) -> dict:
    """Cotizaciones creadas en el período: cuántas se enviaron por correo
    desde el panel (`lastEmailedAt`) y cuántas se convirtieron en pedido."""
    counts = Quote.objects.filter(
        created_at__gte=window.start, created_at__lt=window.end
    ).aggregate(
        created=Count("pk"),
        sent=Count("pk", filter=Q(details__has_key="lastEmailedAt")),
        converted=Count("pk", filter=Q(status=QuoteStatus.CONVERTED)),
    )
    rate = Decimal(counts["converted"]) / counts["created"] * 100 if counts["created"] else ZERO
    return {
        **counts,
        "conversionRate": float(Decimal(rate).quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP)),
    }


def _cart_funnel(window: _Window) -> dict:
    """`checkoutStarted` y `converted` salen de los pedidos del storefront
    (`details.cartId`), que no se borran; `created` y `abandoned`, de las filas de
    `carts` que siguen existiendo (un carrito vaciado se borra)."""
    checkouts = (
        Order.objects.filter(
            created_at__gte=window.start, created_at__lt=window.end, details__has_key="cartId"
        )
        .exclude(details__cartId=None)
        .aggregate(
            started=Count("pk"),
            converted=Count("pk", filter=Q(payment_status__in=CHARGED_PAYMENT_STATUSES)),
        )
    )
    return {
        "created": count_carts_created_between(window.start, window.end),
        "checkoutStarted": checkouts["started"],
        "converted": checkouts["converted"],
        "abandoned": count_abandoned_carts_between(window.start, window.end),
    }


def get_dashboard_analytics(range_key: str | None, now: datetime | None = None) -> tuple[dict, int]:
    range_key = range_key or DEFAULT_ANALYTICS_RANGE
    if range_key not in ANALYTICS_RANGES:
        return {"error": INVALID_RANGE}, 400
    window = _window(range_key, now or timezone.now())
    last_day = timezone.localtime(window.end, store_timezone()).date() - timedelta(days=1)
    return {
        "range": range_key,
        "granularity": window.kind,
        "timeZone": str(store_timezone()),
        "start": window.buckets[0].isoformat(),
        "end": last_day.isoformat(),
        "revenueSeries": _revenue_series(window),
        "kpis": _kpis(window),
        "ordersByStatus": _orders_by_status(window),
        "topProducts": _top_products(window),
        "quoteFunnel": _quote_funnel(window),
        "cartFunnel": _cart_funnel(window),
    }, 200
