from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from apps.checkout.models.payment import Payment


class Refund(models.Model):
    """Un reembolso de un `Payment` de Stripe, pedido desde el panel o hecho
    en el dashboard de Stripe y sincronizado por webhook.

    La fila nace PENDING antes de llamar a Stripe y su id es la
    `idempotency_key`: un reintento de la misma operación no reembolsa dos
    veces. `stripe_refund_id` queda vacío hasta que Stripe responde."""

    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"

    id = models.TextField(primary_key=True)
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.TextField(default=PENDING, db_default=PENDING)
    reason = models.TextField(blank=True, default="", db_default="")
    stripe_refund_id = models.TextField(unique=True, null=True, blank=True)
    # Email del staff o `"stripe"` para los que llegan del dashboard, igual
    # que el actor de la bitácora.
    created_by = models.TextField()
    data = models.JSONField(default=dict, db_default={})
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "refunds"

    def __str__(self) -> str:
        return self.id
