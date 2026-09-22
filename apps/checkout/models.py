"""Stage A models for `orders` and `payments` (design decision #3).

`Order.customer` is a cross-app FK into `apps.customers.Customer`;
`Payment.order` is a same-app FK into `Order`. Both are nullable to match
`on delete set null` in `scripts/schema.sql`. Repricing, Stripe session
creation, and webhook reconciliation are Phase 5's business rules.
"""
from django.db import models


class Order(models.Model):
    id = models.TextField(primary_key=True)
    number = models.TextField(unique=True)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="customer_id",
        related_name="orders",
    )
    status = models.TextField(default="OPEN")
    payment_status = models.TextField(default="UNPAID")
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "orders"
        permissions = [
            ("change_status", "Can change order status"),
            ("cancel_order", "Can cancel orders"),
            ("manage_cores", "Can manage cores"),
            ("manage_returns", "Can manage returns"),
        ]

    def __str__(self) -> str:
        return self.number


class Payment(models.Model):
    id = models.TextField(primary_key=True)
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="order_id",
        related_name="payments",
    )
    provider = models.TextField()
    provider_id = models.TextField(null=True, blank=True)
    status = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "payments"
        permissions = [
            ("take_payment", "Can take payments"),
            ("refund_payment", "Can refund payments"),
            ("view_transaction_id", "Can view payment transaction IDs"),
        ]

    def __str__(self) -> str:
        return self.id
