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

from django.db.models import Count, Q, Sum
from django.db.models.functions import Trunc
from django.utils import timezone

from apps.cart.services import count_abandoned_carts_between, count_carts_created_between
from apps.catalog.services import PricingError, price_lines
from apps.checkout.models import Order, OrderStatus, Payment, Refund, RefundStatus
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
        gross=Sum(net_of_tax("order__data"), default=ZERO),
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
        gross=Sum(net_of_tax("order__data")),
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
    un cobro en el período. Las líneas guardadas se leen con `price_lines`
    (`allow_custom_price=True`), igual que Stripe y la cotización: cubre las
    del storefront (`qty`/`price`) y las de una cotización (`quantity`/
    `unitPrice`). La suma va en Python porque `items` es un array JSON y el
    ORM no lo despliega sin SQL crudo; es una sola consulta."""
    order_ids = _charged_payments(window.start, window.end).values("order_id")
    item_lists = Order.objects.filter(pk__in=order_ids).values_list("data__items", flat=True)
    totals: dict[str, dict] = {}
    for items in item_lists:
        for item in items if isinstance(items, list) else []:
            try:
                (line,) = price_lines([item], allow_custom_price=True, max_quantity=None).lines
            except (PricingError, ValueError):
                continue
            product_id = line.product_id
            key = str(product_id or item.get("partNumber") or item.get("title") or "")
            if not key:
                continue
            row = totals.setdefault(
                key,
                {
                    "productId": product_id,
                    "title": item.get("title") or "",
                    "partNumber": item.get("partNumber") or "",
                    "units": 0,
                    "revenue": ZERO,
                },
            )
            row["units"] += line.quantity
            row["revenue"] += line.line_total
    ranked = sorted(totals.values(), key=lambda row: (-row["revenue"], -row["units"], row["title"]))
    return [{**row, "revenue": money(row["revenue"])} for row in ranked[:TOP_PRODUCTS_LIMIT]]


def _quote_funnel(window: _Window) -> dict:
    """Cotizaciones creadas en el período: cuántas se enviaron por correo
    desde el panel (`lastEmailedAt`) y cuántas se convirtieron en pedido."""
    counts = Quote.objects.filter(
        created_at__gte=window.start, created_at__lt=window.end
    ).aggregate(
        created=Count("pk"),
        sent=Count("pk", filter=Q(data__has_key="lastEmailedAt")),
        converted=Count("pk", filter=Q(status=QuoteStatus.CONVERTED)),
    )
    rate = Decimal(counts["converted"]) / counts["created"] * 100 if counts["created"] else ZERO
    return {
        **counts,
        "conversionRate": float(Decimal(rate).quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP)),
    }


def _cart_funnel(window: _Window) -> dict:
    """`checkoutStarted` y `converted` salen de los pedidos del storefront
    (`data.cartId`), que no se borran; `created` y `abandoned`, de las filas de
    `carts` que siguen existiendo (un carrito vaciado se borra)."""
    checkouts = (
        Order.objects.filter(
            created_at__gte=window.start, created_at__lt=window.end, data__has_key="cartId"
        )
        .exclude(data__cartId=None)
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
