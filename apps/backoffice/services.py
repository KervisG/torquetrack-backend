"""Reglas de `admin/dashboard` y `admin/activity`, portadas de
`app/api/admin/dashboard/route.ts` y `app/api/admin/activity/route.ts`.
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.fields.json import KT
from django.db.models.functions import Cast
from django.utils import timezone

from apps.backoffice.models import ActivityLog
from apps.cart.models import Cart
from apps.checkout.models import Order
from apps.quotes.models import Quote

# Un carrito sin cambios por más de esta ventana cuenta como abandonado.
CART_IDLE_WINDOW = timedelta(minutes=30)

# `data.totals.total` es un número JSON; se suma como numeric (no float) para
# no arrastrar error de coma flotante, igual que el `::numeric` del legado.
_ORDER_TOTAL = Cast(
    KT("data__totals__total"), DecimalField(max_digits=20, decimal_places=6)
)


def get_dashboard_counts() -> dict:
    now = timezone.now()
    idle_cutoff = now - CART_IDLE_WINDOW
    # El legado comparaba `created_at::date = current_date` con la sesión de
    # Postgres en UTC; el día de hoy se calcula en UTC por la misma razón.
    today_start = datetime.combine(now.astimezone(UTC).date(), time.min, UTC)

    quotes = Quote.objects.aggregate(
        active=Count("pk", filter=Q(status="ACTIVE")),
        building=Count("pk", filter=Q(status="BUILDING")),
    )
    carts = Cart.objects.aggregate(
        active=Count("pk", filter=Q(updated_at__gt=idle_cutoff)),
        abandoned=Count("pk", filter=Q(updated_at__lte=idle_cutoff)),
    )
    sales_today = Order.objects.filter(
        created_at__gte=today_start,
        created_at__lt=today_start + timedelta(days=1),
        payment_status="PAID",
    ).aggregate(total=Sum(_ORDER_TOTAL, default=Decimal(0)))["total"]

    return {
        "counts": {
            "orders": Order.objects.count(),
            "activeQuotes": quotes["active"],
            "buildingQuotes": quotes["building"],
            "activeCarts": carts["active"],
            "abandonedCarts": carts["abandoned"],
            "salesToday": float(sales_today),
        }
    }


def list_recent_activity(limit: int = 250) -> list[dict]:
    """Mirror `select * from activity_logs order by created_at desc limit
    250`'s raw-row shape (snake_case column names, as node-pg returns
    them) rather than the model's usual camelCase serialization."""
    logs = ActivityLog.objects.order_by("-created_at")[:limit]
    return [
        {
            "id": log.id,
            "actor_id": log.actor_id,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "data": log.data,
            "created_at": log.created_at,
        }
        for log in logs
    ]
