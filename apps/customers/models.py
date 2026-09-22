"""Stage A model for the `customers` table (design decisions #3 and #9).

Tax-exemption certificates stay base64-encoded inside `data` jsonb for now
(decision #9) — no object storage is introduced by this model.
"""
from django.db import models


class Customer(models.Model):
    id = models.TextField(primary_key=True)
    email = models.TextField(unique=True, null=True, blank=True)
    password_hash = models.TextField(null=True, blank=True)
    data = models.JSONField(default=dict)
    portal_status = models.TextField(default="NOT ACTIVATED")
    activation_token_hash = models.TextField(null=True, blank=True)
    activation_expires_at = models.DateTimeField(null=True, blank=True)
    tax_status = models.TextField(default="NOT SUBMITTED")
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "customers"
        permissions = [
            ("review_tax_exemption", "Can review tax exemptions"),
        ]

    def __str__(self) -> str:
        return self.email or self.id
