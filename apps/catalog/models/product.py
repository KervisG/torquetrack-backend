from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class Product(models.Model):
    id = models.TextField(primary_key=True)
    data = models.JSONField(default=dict)
    active = models.BooleanField(default=True, db_default=True)
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "products"
        indexes = [GinIndex(fields=["data"], name="idx_products_data")]
        permissions = [
            ("edit_pricing", "Can edit pricing"),
            ("view_costs", "Can view costs"),
        ]

    def __str__(self) -> str:
        return self.id
