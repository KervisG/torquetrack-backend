from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from apps.checkout.models.order import Order


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
    status = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, db_default=0)
    data = models.JSONField(default=dict, db_default={})
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
