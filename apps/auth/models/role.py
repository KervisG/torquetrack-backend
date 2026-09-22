"""Roles de staff. Se crean en `/admin/` con nombre, slug y el selector
de Permission de Django. `full_access` es el Admin.
"""
from django.contrib.auth.models import Permission
from django.db import models


class Role(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    full_access = models.BooleanField(default=False)
    permissions = models.ManyToManyField(
        Permission,
        blank=True,
        related_name="staff_roles",
    )

    class Meta:
        db_table = "roles"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class EmployeeRole(models.Model):
    """Une `users.id` con un Role. Sin FK SQL a `users` porque esa tabla
    la crea `schema.sql` después de `migrate`.
    """

    user_id = models.TextField(unique=True)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")

    class Meta:
        db_table = "employee_roles"

    def __str__(self) -> str:
        return f"{self.user_id} → {self.role.slug}"
