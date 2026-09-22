"""Roles en el admin de Django: nombre, slug y el selector de permisos.

No se escriben strings tipo `dashboard.view`. Se elige
`Activity log — Can view dashboard`.
"""
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.db.models import Q

from apps.auth.models import EmployeeRole, Role
from apps.auth.permission_catalog import STAFF_PERMISSIONS


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


@admin.register(EmployeeRole)
class EmployeeRoleAdmin(admin.ModelAdmin):
    list_display = ("user_id", "role")
    list_filter = ("role",)
