"""`dashboard` no tiene modelos: solo lee pedidos, cotizaciones y carritos de
sus apps dueñas y nunca escribe."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.fields.json import KT
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from apps.cart.models import CartStatus
from apps.cart.services import count_carts_by_status
from apps.checkout.models import Order, Refund, RefundStatus
from apps.checkout.services import CHARGED_PAYMENT_STATUSES
from apps.common.numbers import money
from apps.quotes.models import Quote, QuoteStatus
from apps.quotes.services import unexpired_quotes_q

_NUMERIC = DecimalField(max_digits=20, decimal_places=6)


def _order_total(key: str):
    """`data.totals.<key>` del pedido como numeric (no float), para no
    arrastrar error de coma flotante; una clave ausente suma 0."""
    return Coalesce(Cast(KT(f"data__totals__{key}"), _NUMERIC), Value(Decimal(0), _NUMERIC))


# Lo vendido sin impuesto: el impuesto se cobra por cuenta del estado.
_NET_OF_TAX = _order_total("subtotal") + _order_total("core") + _order_total("shipping")


def net_sales_between(start, end) -> Decimal:
    """Ventas netas del período [start, end), en `Decimal`:

    subtotal + core + envío de los pedidos con un pago cobrado en el período
    (`Payment.paid_at`, no el `created_at` del pedido; un pago reembolsado
    sigue contando como cobrado, `CHARGED_PAYMENT_STATUSES`), menos los
    reembolsos `SUCCEEDED` emitidos en el período (`Refund.created_at`),
    sean de pagos del período o de antes. El impuesto nunca entra; un
    reembolso resta su monto completo porque `Refund` no separa impuesto.
    """
    # Un solo `filter()` sobre la relación: el join deja una fila por pago
    # cobrado en el período, así un cobro duplicado suma dos veces (se cobró
    # dos veces) hasta que su reembolso lo descuente.
    charged = Order.objects.filter(
        payments__status__in=CHARGED_PAYMENT_STATUSES,
        payments__paid_at__gte=start,
        payments__paid_at__lt=end,
    ).aggregate(total=Sum(_NET_OF_TAX, default=Decimal(0)))["total"]
    refunded = Refund.objects.filter(
        status=RefundStatus.SUCCEEDED, created_at__gte=start, created_at__lt=end
    ).aggregate(total=Sum("amount", default=Decimal(0)))["total"]
    return charged - refunded


def get_dashboard_counts() -> dict:
    now = timezone.now()
    # "Hoy" es el día calendario en UTC, sin importar la zona horaria del
    # servidor ni la del usuario.
    today_start = datetime.combine(now.astimezone(UTC).date(), time.min, UTC)

    # Una cotización vencida que todavía no pasó por `expire_quotes` no cuenta.
    quotes = Quote.objects.filter(unexpired_quotes_q()).aggregate(
        active=Count("pk", filter=Q(status=QuoteStatus.ACTIVE)),
        building=Count("pk", filter=Q(status=QuoteStatus.BUILDING)),
    )
    carts = count_carts_by_status()
    sales_today = net_sales_between(today_start, today_start + timedelta(days=1))

    return {
        "counts": {
            "orders": Order.objects.count(),
            "activeQuotes": quotes["active"],
            "buildingQuotes": quotes["building"],
            "activeCarts": carts[CartStatus.ACTIVE],
            "abandonedCarts": carts[CartStatus.ABANDONED],
            "salesToday": money(sales_today),
        }
    }
