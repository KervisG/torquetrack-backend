"""Stage A model for the `carts` table (design decision #3).

Upsert-by-client-UUID and delete-on-empty (`cart/sync`) are Phase 5's
business rules; this model only binds the existing columns.
"""
from django.db import models


class Cart(models.Model):
    id = models.TextField(primary_key=True)
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "carts"

    def __str__(self) -> str:
        return self.id
