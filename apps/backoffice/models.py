"""Modelo de la bitácora `activity_logs`.

`actor_id` no es FK: guarda el email del staff o un actor de sistema como
`"stripe"`, y la fila tiene que sobrevivir aunque el usuario se borre.
"""
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class ActivityLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    actor_id = models.TextField(null=True, blank=True)
    action = models.TextField()
    entity_type = models.TextField(null=True, blank=True)
    entity_id = models.TextField(null=True, blank=True)
    data = models.JSONField(default=dict, db_default={})
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "activity_logs"
        permissions = [
            ("view_dashboard", "Can view dashboard"),
        ]

    def __str__(self) -> str:
        return f"{self.action}:{self.entity_id}"
