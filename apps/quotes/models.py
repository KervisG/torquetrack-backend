"""Modelo de cotizaciones (`quotes`).

`customer` apunta a `customers.Customer` y queda en NULL si se borra el
perfil. Los tokens del enlace público viven dentro de `data`. `number` lo
asigna `next_quote_number` y la base garantiza que es único.
"""
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


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
    status = models.TextField(default="BUILDING", db_default="BUILDING")
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
