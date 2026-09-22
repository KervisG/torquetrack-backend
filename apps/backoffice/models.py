"""Stage A model for the `activity_logs` table (design decision #3).

Only the `ActivityLog` binding needed for Phase 5's Stripe webhook audit
write (`app/api/webhooks/stripe/route.ts` inserts one row on
`PAYMENT_PAID`) is added here. The `admin/activity` read endpoint that
displays this table is explicitly Phase 7 scope per the tasks artifact —
this model does not implement that endpoint.
"""
from django.db import models


class ActivityLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    actor_id = models.TextField(null=True, blank=True)
    action = models.TextField()
    entity_type = models.TextField(null=True, blank=True)
    entity_id = models.TextField(null=True, blank=True)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "activity_logs"
        permissions = [
            ("view_dashboard", "Can view dashboard"),
        ]

    def __str__(self) -> str:
        return f"{self.action}:{self.entity_id}"
