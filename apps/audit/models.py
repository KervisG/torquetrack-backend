"""Solo `apps/audit` conoce este modelo: el resto de las apps escribe con
`record_activity`."""
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

    def __str__(self) -> str:
        return f"{self.action}:{self.entity_id}"
