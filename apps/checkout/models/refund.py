from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from apps.checkout.models.payment import Payment


class RefundStatus(models.TextChoices):
    # `CANCELED` con una sola L por compatibilidad con las filas existentes;
    # `Payment` usa `CANCELLED`.
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class Refund(models.Model):
    """Un reembolso (o anulación) de un `Payment`, pedido desde el panel o
    hecho en el Merchant Interface de Authorize.net y sincronizado por webhook.

    La fila nace PENDING antes de llamar a la pasarela y su id viaja como
    `invoiceNumber` del reembolso, así el webhook la reconoce.
    `provider_refund_id` queda vacío hasta que la pasarela responde: es el id
    de la transacción de reembolso, o `VOID-<id del cobro>` en una anulación."""

    id = models.TextField(primary_key=True)
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.TextField(
        choices=RefundStatus, default=RefundStatus.PENDING, db_default=RefundStatus.PENDING
    )
    reason = models.TextField(blank=True, default="", db_default="")
    provider_refund_id = models.TextField(unique=True, null=True, blank=True)
    # Email del staff o `"authorize_net"` para los que llegan del Merchant
    # Interface, igual que el actor de la bitácora.
    created_by = models.TextField()
    data = models.JSONField(default=dict, db_default={})
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "refunds"

    def __str__(self) -> str:
        return self.id
