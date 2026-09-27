"""`dashboard` no tiene modelos: solo lee pedidos, cotizaciones y carritos de
sus apps dueñas y nunca escribe."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.fields.json import KT
from django.db.models.functions import Cast
from django.utils import timezone

from apps.cart.services import count_carts_by_status
from apps.checkout.models import Order
from apps.quotes.models import Quote
from apps.quotes.services import unexpired_quotes_q

# `data.totals.total` es un número JSON; se suma como numeric (no float) para
# no arrastrar error de coma flotante.
_ORDER_TOTAL = Cast(
    KT("data__totals__total"), DecimalField(max_digits=20, decimal_places=6)
)


def get_dashboard_counts() -> dict:
    now = timezone.now()
    # "Hoy" es el día calendario en UTC, sin importar la zona horaria del
    # servidor ni la del usuario.
    today_start = datetime.combine(now.astimezone(UTC).date(), time.min, UTC)

    # Una cotización vencida que todavía no pasó por `expire_quotes` no cuenta.
    quotes = Quote.objects.filter(unexpired_quotes_q()).aggregate(
        active=Count("pk", filter=Q(status="ACTIVE")),
        building=Count("pk", filter=Q(status="BUILDING")),
    )
    carts = count_carts_by_status()
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
            "activeCarts": carts["ACTIVE"],
            "abandonedCarts": carts["ABANDONED"],
            "salesToday": float(sales_today),
        }
    }
