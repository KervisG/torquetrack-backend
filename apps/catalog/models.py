"""Stage A models for `products` and `applications` (design decision #3)."""
from django.db import models


class Product(models.Model):
    id = models.TextField(primary_key=True)
    data = models.JSONField(default=dict)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "products"

    def __str__(self) -> str:
        return self.id


class Application(models.Model):
    data = models.JSONField(default=dict)

    class Meta:
        managed = False
        db_table = "applications"

    def __str__(self) -> str:
        return str(self.pk)
