"""El `id` lo genera el servidor y vive en la sesión (`cart_id`); el cliente
nunca lo elige."""
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class Cart(models.Model):
    id = models.TextField(primary_key=True)
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "carts"

    def __str__(self) -> str:
        return self.id
