"""La cuenta: email y contraseña. Todo el que se registra es cliente.

El acceso al panel lo da un `Role` que asigna un admin; sin Role no hay
panel aunque la cuenta esté activa. El perfil comercial vive en
`apps.customers.Customer` (`user.customer`).
"""
import secrets

from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


def new_user_id() -> str:
    """Mismo formato que el resto de ids del dominio: prefijo + 12 hex."""
    return "U" + secrets.token_hex(6).upper()


def normalize_email(raw) -> str:
    return str(raw or "").strip().lower()


class User(models.Model):
    id = models.TextField(primary_key=True, default=new_user_id)
    # Se guarda siempre en minúsculas, así el `unique` también cubre
    # variantes de mayúsculas del mismo correo.
    email = models.TextField(unique=True)
    password_hash = models.TextField()
    role = models.ForeignKey(
        "tt_auth.Role",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="users",
    )
    active = models.BooleanField(default=True)
    first_name = models.TextField(null=True, blank=True)
    last_name = models.TextField(null=True, blank=True)
    display_name = models.TextField(null=True, blank=True)
    # Cuándo se probó que la persona controla `email` (enlace de verificación
    # o invitación al portal). Sin verificar no se vincula el historial de
    # compras como invitado.
    email_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "users"
        default_permissions = ()
        # `view_dashboard` vive aquí aunque el dashboard no sea de `auth`:
        # `apps.dashboard` no tiene modelos y el proyecto retiró el marcador
        # sin tabla (`TorqueTrackPermission`, migración 0006), así que todo
        # permiso cuelga de un modelo real. `dashboard.view` es el permiso de
        # entrada al panel de staff, que ya gobierna `auth` (Roles y
        # `manage_users`); colgarlo de `Order`, `Quote` o `Cart` ataría el
        # agregado a una de sus fuentes de forma arbitraria.
        permissions = [
            ("manage_users", "Can manage users"),
            ("view_dashboard", "Can view dashboard"),
        ]

    # DRF y los helpers de Django preguntan esto sobre `request.user`.
    is_authenticated = True
    is_anonymous = False

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        self.email = normalize_email(self.email)
        super().save(*args, **kwargs)

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
        return composed or self.email
