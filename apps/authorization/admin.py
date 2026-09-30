"""En `User` solo se asigna el Role y se activa o desactiva la cuenta: nadie
crea cuentas ni cambia contraseñas por aquí (toda persona se registra como
cliente en la tienda). `/django-admin/` solo lo abre un
usuario activo con Role de acceso total (`User.is_staff`).

Un cambio de Role o una baja no necesita cortar sesiones a mano: la sesión se
revalida en cada request (`ModelBackend.get_user` rechaza al inactivo y
`User.has_perm` lee el Role)."""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Q

from apps.authorization.models import Role
from apps.authorization.permissions import STAFF_PERMISSIONS


def staff_permission_queryset():
    query = Q()
    for _code, app_label, model, codename in STAFF_PERMISSIONS:
        query |= Q(
            content_type__app_label=app_label,
            content_type__model=model,
            codename=codename,
        )
    return Permission.objects.filter(query).select_related("content_type")


def _permission_label(permission: Permission) -> str:
    model = permission.content_type.name
    return f"{model} — {permission.name}"


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "full_access")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("permissions",)
    fields = ("name", "slug", "full_access", "permissions")

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "permissions":
            kwargs["queryset"] = staff_permission_queryset()
            field = super().formfield_for_manytomany(db_field, request, **kwargs)
            field.label_from_instance = _permission_label
            field.help_text = (
                "Move the permissions this role should have. "
                "If Full access is checked, this list is ignored."
            )
            return field
        return super().formfield_for_manytomany(db_field, request, **kwargs)


# `get_user_model()` y no un import: esta app está debajo de
# `apps.authentication` y nunca la importa.
@admin.register(get_user_model())
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "role", "active", "created_at")
    list_filter = ("role", "active")
    search_fields = ("email", "first_name", "last_name")
    fields = ("id", "email", "first_name", "last_name", "role", "active", "created_at")
    readonly_fields = ("id", "email", "created_at")

    def has_add_permission(self, request):
        return False
