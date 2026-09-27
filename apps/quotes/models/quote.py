"""El token del enlace público vive dentro de `data`."""
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class QuoteStatus(models.TextChoices):
    """`EXPIRED` se persiste solo con `expire_quotes`; al leer, el vencimiento
    se calcula con `effective_quote_status`."""

    BUILDING = "BUILDING"
    ACTIVE = "ACTIVE"
    CONTACTED = "CONTACTED"
    EXPIRED = "EXPIRED"
    CONVERTED = "CONVERTED"
    LOST = "LOST"


class Quote(models.Model):
    id = models.TextField(primary_key=True)
    number = models.TextField(unique=True)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotes",
    )
    status = models.TextField(
        choices=QuoteStatus, default=QuoteStatus.BUILDING, db_default=QuoteStatus.BUILDING
    )
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "quotes"
        permissions = [
            ("send_quote", "Can send quotes"),
            ("convert_quote", "Can convert quotes"),
        ]

    def __str__(self) -> str:
        return self.number
