"""Un `User` con Role es staff; el Role es la única fuente de permisos."""
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
