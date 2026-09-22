"""Binding Stage A de la tabla `users`.

`managed = False`: Django no crea ni altera esa tabla.
"""
from django.db import models


class User(models.Model):
    id = models.TextField(primary_key=True)
    username = models.TextField(unique=True)
    password_hash = models.TextField()
    role = models.TextField(default="authorized")
    active = models.BooleanField(default=True)
    first_name = models.TextField(null=True, blank=True)
    last_name = models.TextField(null=True, blank=True)
    display_name = models.TextField(null=True, blank=True)
    permissions = models.JSONField(default=list)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "users"
        default_permissions = ()
        permissions = [
            ("manage_users", "Can manage users"),
        ]

    def __str__(self) -> str:
        return self.username

    def given_names(self) -> tuple[str, str]:
        first = (self.first_name or "").strip()
        last = (self.last_name or "").strip()
        if first or last:
            return first, last
        parts = (self.display_name or "").strip().split(None, 1)
        if not parts:
            return "", ""
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], parts[1]

    def full_name(self) -> str:
        first, last = self.given_names()
        composed = " ".join(part for part in (first, last) if part)
        return composed or self.username
