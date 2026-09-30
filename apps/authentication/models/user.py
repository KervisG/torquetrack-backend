"""Todo el que se registra es cliente: sin un `Role` asignado por un admin no
hay acceso al panel aunque la cuenta esté activa.

Es el `AUTH_USER_MODEL`: sesión, login y hash de contraseña son los de
`django.contrib.auth`, con el `ModelBackend` por defecto solo para autenticar.
No hereda `PermissionsMixin` porque el Role es la única fuente de permisos:
`User.has_perm` lee solo el Role y así no existen las tablas de grupos ni de
permisos por usuario.
"""
import secrets

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import Permission
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from apps.authorization.models import ADMIN_ROLE_SLUG, Role


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


class UserManager(BaseUserManager):
    def get_queryset(self):
        # El Role se lee en casi todo request (permisos, `isStaff`): como
        # `ModelBackend.get_user` usa `_default_manager`, así `request.user`
        # lo trae en la misma consulta. Un `select_for_update` sobre `User`
        # necesita `of=("self",)`: Postgres no bloquea el lado nullable del
        # LEFT JOIN.
        return super().get_queryset().select_related("role")

    def get_by_natural_key(self, username):
        # El email se guarda en minúsculas: sin normalizar aquí, `Ana@x.com`
        # no encontraría la cuenta en el login ni en `createsuperuser`.
        return self.get(**{self.model.USERNAME_FIELD: normalize_email(username)})

    def create_user(self, email, password=None, **extra_fields):
        user = self.model(email=normalize_email(email), **extra_fields)
        # Sin `password` queda un hash inutilizable, igual que en Django.
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """`is_superuser` sale del Role: el superusuario recibe el Role de
        acceso total que siembran las migraciones (`admin`)."""
        role, _ = Role.objects.get_or_create(
            slug=ADMIN_ROLE_SLUG, defaults={"name": "Admin", "full_access": True}
        )
        if not role.full_access:
            raise ValueError("The admin role does not have full access; fix it in /admin/.")
        extra_fields.setdefault("email_verified_at", timezone.now())
        return self.create_user(email, password, role=role, **extra_fields)


class User(AbstractBaseUser):
    id = models.TextField(primary_key=True, default=new_user_id)
    # Se guarda siempre en minúsculas, así el `unique` también cubre
    # variantes de mayúsculas del mismo correo.
    email = models.TextField(unique=True)
    role = models.ForeignKey(
        "authorization.Role",
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

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"
        # Los permisos del panel cuelgan de los modelos de dominio y del Role
        # (`apps.authorization`); `User` no concede ni declara ninguno.
        default_permissions = ()

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        self.email = normalize_email(self.email)
        super().save(*args, **kwargs)

    # `active` es la columna histórica; Django (backends, admin, DRF) pregunta
    # por `is_active`.
    @property
    def is_active(self) -> bool:
        return self.active

    @property
    def is_staff(self) -> bool:
        """Acceso a `/django-admin/` de Django, solo para el Role de acceso total.
        El staff del panel (cualquier Role) es `is_staff_user`."""
        return self.active and self.role_id is not None and self.role.full_access

    @property
    def is_superuser(self) -> bool:
        return self.is_staff

    # Mismo contrato que `PermissionsMixin`, sin sus tablas. No se pregunta a
    # `AUTHENTICATION_BACKENDS`: `ModelBackend` buscaría `user_permissions` y
    # `groups`, que este `User` no tiene, y solo se usa para autenticar.
    def _permission_role(self):
        if not self.is_active or self.role_id is None:
            return None
        return self.role

    def get_all_permissions(self, obj=None) -> set[str]:
        """`app_label.codename` que concede el Role. Se cachea en el objeto,
        que el middleware vuelve a cargar en cada request: un cambio de Role
        rige desde el request siguiente."""
        role = self._permission_role()
        if role is None or obj is not None:
            return set()
        if not hasattr(self, "_role_perm_cache"):
            permissions = Permission.objects.all() if role.full_access else role.permissions.all()
            pairs = permissions.values_list("content_type__app_label", "codename")
            self._role_perm_cache = {f"{app_label}.{codename}" for app_label, codename in pairs}
        return self._role_perm_cache

    def has_perm(self, perm, obj=None) -> bool:
        role = self._permission_role()
        if role is None or obj is not None:
            return False
        return role.full_access or perm in self.get_all_permissions()

    def has_perms(self, perm_list, obj=None) -> bool:
        return all(self.has_perm(perm, obj) for perm in perm_list)

    def has_module_perms(self, app_label) -> bool:
        role = self._permission_role()
        if role is None:
            return False
        return role.full_access or any(
            perm.split(".", 1)[0] == app_label for perm in self.get_all_permissions()
        )

    def given_names(self) -> tuple[str, str]:
        first = (self.first_name or "").strip()
        last = (self.last_name or "").strip()
        if first or last:
            return first, last
        return split_full_name(self.display_name)

    def full_name(self) -> str:
        return compose_display_name(*self.given_names()) or self.email
