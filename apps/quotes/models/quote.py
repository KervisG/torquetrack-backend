"""El token del enlace público vive dentro de `details`."""
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from apps.common.line_items import (
    DocumentTotals,
    LineItem,
    LineItemsMixin,
    line_item_constraints,
    total_constraints,
)


class QuoteStatus(models.TextChoices):
    """`EXPIRED` se persiste solo con `expire_quotes`; al leer, el vencimiento
    se calcula con `effective_quote_status`."""

    BUILDING = "BUILDING"
    ACTIVE = "ACTIVE"
    CONTACTED = "CONTACTED"
    EXPIRED = "EXPIRED"
    CONVERTED = "CONVERTED"
    LOST = "LOST"


class Quote(LineItemsMixin, DocumentTotals):
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
    # Lo que no tiene columna; las líneas viven en `QuoteItem` y `data` las suma.
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "quotes"
        constraints = total_constraints("quotes")
        permissions = [
            ("send_quote", "Can send quotes"),
            ("convert_quote", "Can convert quotes"),
        ]

    def __str__(self) -> str:
        return self.number


class QuoteItem(LineItem):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="items")

    class Meta(LineItem.Meta):
        db_table = "quote_items"
        constraints = [
            models.UniqueConstraint(fields=["quote", "position"], name="quote_items_position"),
            *line_item_constraints("quote_items"),
        ]
