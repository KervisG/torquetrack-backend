"""Todo el que se registra es cliente: sin un `Role` asignado por un admin no
hay acceso al panel aunque la cuenta esté activa."""
import secrets

from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


def new_user_id() -> str:
    """Mismo formato que el resto de ids del dominio: prefijo + 12 hex."""
    return "U" + secrets.token_hex(6).upper()


def normalize_email(raw) -> str:
    return str(raw or "").strip().lower()


def split_full_name(name) -> tuple[str, str]:
    """Primera palabra como nombre y el resto como apellido."""
    parts = str(name or "").strip().split(None, 1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def compose_display_name(first_name: str, last_name: str) -> str:
    return " ".join(part for part in (first_name, last_name) if part)


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
        # `view_dashboard` vive aquí porque `apps.dashboard` no tiene modelos y
        # todo permiso cuelga de un modelo real. Es el permiso de entrada al
        # panel, que ya gobierna `auth`; colgarlo de `Order`, `Quote` o `Cart`
        # ataría el agregado a una de sus fuentes de forma arbitraria.
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
        return split_full_name(self.display_name)

    def full_name(self) -> str:
        return compose_display_name(*self.given_names()) or self.email
