from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from apps.checkout.models.order import Order


class PaymentStatus(models.TextChoices):
    """Un intento de cobro nace PENDING; PAID, PARTIALLY_REFUNDED y REFUNDED
    cuentan como cobrado (`CHARGED_PAYMENT_STATUSES`)."""

    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class Payment(models.Model):
    id = models.TextField(primary_key=True)
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    provider = models.TextField()
    provider_id = models.TextField(null=True, blank=True)
    status = models.TextField(choices=PaymentStatus)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, db_default=0)
    data = models.JSONField(default=dict, db_default={})
    # Momento en que Stripe confirmó el cobro; el dashboard suma las ventas
    # del día por esta fecha y no por la creación del pedido.
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "payments"
        permissions = [
            ("take_payment", "Can take payments"),
            ("refund_payment", "Can refund payments"),
            ("view_transaction_id", "Can view payment transaction IDs"),
        ]

    def __str__(self) -> str:
        return self.id
