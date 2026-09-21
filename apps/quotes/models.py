"""Stage A model for `quotes` (design decision #3).

`customer` is a cross-app FK into `apps.customers.Customer`, nullable to
match `on delete set null`. Magic-link tokens live inside `data` jsonb for
now (Stage B backfill types them later, per design decision #4).
"""
from django.db import models


class Quote(models.Model):
    id = models.TextField(primary_key=True)
    number = models.TextField(unique=True)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="customer_id",
        related_name="quotes",
    )
    status = models.TextField(default="BUILDING")
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "quotes"

    def __str__(self) -> str:
        return self.number
