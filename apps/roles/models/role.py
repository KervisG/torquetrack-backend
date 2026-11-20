"""Un `User` con Role es staff; el Role es la única fuente de permisos.

No importa el `User`: lo alcanza con `get_user_model()` y con la relación
inversa `role.users`.
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
        # Los dos permisos que no tienen un modelo de dominio propio cuelgan
        # del Role, que gobierna el acceso al panel: `users.manage` es la
        # gestión de usuarios y roles de esta app, y `dashboard.view` es la
        # entrada al panel (`apps.dashboard` no tiene modelos). Colgarlos de
        # `User` ataría la autorización a `apps.auth`.
        permissions = [
            ("manage_users", "Can manage users"),
            ("view_dashboard", "Can view dashboard"),
        ]

    def __str__(self) -> str:
        return self.name
