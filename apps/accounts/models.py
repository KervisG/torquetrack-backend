"""Stage A model for the `users` table (design decision #3).

`managed = False`: Django never creates, alters, or drops this table. The
frozen Next.js app and Django both read/write the same rows during the
strangler migration (design decision #2). Auth/RBAC behavior (custom
password hasher, session cookies, permission mapping) is Phase 3's concern;
this model only binds the existing columns.
"""
from django.db import models


class User(models.Model):
    id = models.TextField(primary_key=True)
    username = models.TextField(unique=True)
    password_hash = models.TextField()
    role = models.TextField(default="authorized")
    active = models.BooleanField(default=True)
    display_name = models.TextField(null=True, blank=True)
    permissions = models.JSONField(default=list)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "users"

    def __str__(self) -> str:
        return self.username


class TorqueTrackPermission(models.Model):
    """Marker model with no real database table (`managed = False`, no
    `db_table` — Django never creates one). It exists ONLY so the 26
    legacy permission strings from `lib/permissions.ts` have a single,
    named `ContentType` to hang their Django `Permission` codenames on
    (design decision #6, task 3.3) — the standard pattern for permissions
    that are not tied to any one real model. See
    `apps/accounts/migrations/0002_rbac_permissions.py`.
    """

    class Meta:
        managed = False
        default_permissions = ()
        verbose_name = "TorqueTrack permission"
