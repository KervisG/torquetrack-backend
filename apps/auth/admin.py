"""Roles y cuentas en el admin de Django.

Los Roles se crean aquí con nombre, slug y el selector de permisos (no se
escriben strings tipo `dashboard.view`, se elige
`Activity log — Can view dashboard`). En `User` solo se asigna el Role y
se activa o desactiva la cuenta: el alta es por `/api/register/` o
`POST /api/admin/users/`, y las contraseñas nunca se tocan desde aquí.
"""
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.db.models import Q

from apps.auth.models import Role, User
from apps.auth.permission_catalog import STAFF_PERMISSIONS
from apps.auth.sessions import revoke_user_sessions


def staff_permission_queryset():
    query = Q()
    for _legacy, app_label, model, codename in STAFF_PERMISSIONS:
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


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "role", "active", "created_at")
    list_filter = ("role", "active")
    search_fields = ("email", "first_name", "last_name")
    fields = ("id", "email", "first_name", "last_name", "role", "active", "created_at")
    readonly_fields = ("id", "email", "created_at")

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Igual que en `/api/admin/users/`: un cambio de Role o una baja no
        # puede convivir con sesiones abiertas con el acceso anterior.
        if change and ({"role", "active"} & set(form.changed_data)):
            revoke_user_sessions(obj.pk)
