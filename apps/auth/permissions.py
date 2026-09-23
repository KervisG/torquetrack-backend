"""Permiso de DRF. La fuente de verdad es el Role y los Permission
colgados de los modelos de dominio.
"""
from rest_framework.permissions import BasePermission

from apps.auth.models import EmployeeRole, Role, User
from apps.auth.permission_catalog import (
    DEFAULT_ROLE_LEGACY,
    DJANGO_TO_LEGACY,
    LEGACY_TO_DJANGO,
    resolve_staff_permission,
)

PERMISSIONS = list(LEGACY_TO_DJANGO)
DEFAULT_EMPLOYEE_PERMISSIONS = list(DEFAULT_ROLE_LEGACY)

ADMIN_ROLE_SLUG = "admin"
EMPLOYEE_ROLE_SLUG = "employee"

ROLE_SLUG_ALIASES = {
    "admin": ADMIN_ROLE_SLUG,
    "authorized": EMPLOYEE_ROLE_SLUG,
    "employee": EMPLOYEE_ROLE_SLUG,
}

_UNSET = object()


def normalize_permissions(value) -> list[str]:
    """Deduplica y deja solo strings del catálogo legado."""
    if not isinstance(value, list):
        value = []
    seen: dict[str, None] = {}
    for raw in value:
        candidate = str(raw)
        if candidate in LEGACY_TO_DJANGO:
            seen.setdefault(candidate, None)
    return list(seen)


def legacy_role_label(role: Role) -> str:
    return "admin" if role.full_access else "authorized"


def stored_permissions_for_role(role: Role) -> list[str]:
    if role.full_access:
        return ["*"]
    return permission_strings_for_role(role)


def permission_strings_for_role(role: Role) -> list[str]:
    if role.full_access:
        return ["*"]
    pairs = role.permissions.values_list("content_type__app_label", "codename")
    return [
        DJANGO_TO_LEGACY[pair]
        for pair in pairs
        if pair in DJANGO_TO_LEGACY
    ]


def get_staff_role(user) -> Role | None:
    cached = getattr(user, "_staff_role", _UNSET)
    if cached is not _UNSET:
        return cached
    assignment = (
        EmployeeRole.objects.filter(user_id=user.pk).select_related("role").first()
    )
    role = assignment.role if assignment else None
    user._staff_role = role
    return role


def attach_staff_roles(users: list) -> None:
    """Una query para el listado; evita N+1 al serializar."""
    if not users:
        return
    assignments = {
        row.user_id: row.role
        for row in EmployeeRole.objects.filter(
            user_id__in=[user.pk for user in users]
        ).select_related("role")
    }
    for user in users:
        user._staff_role = assignments.get(user.pk)


def assign_staff_role(user_id: str, role: Role) -> None:
    EmployeeRole.objects.update_or_create(user_id=user_id, defaults={"role": role})


def role_by_slug(slug: str) -> Role | None:
    return Role.objects.filter(slug=slug).first()


def resolve_role_slug(raw: str) -> str:
    key = str(raw).strip().lower()
    return ROLE_SLUG_ALIASES.get(key, key)


def role_from_payload(raw) -> Role | None:
    if raw is None or raw == "":
        return None
    return role_by_slug(resolve_role_slug(str(raw)))


def is_full_access(user) -> bool:
    role = get_staff_role(user)
    if role is not None:
        return role.full_access
    return str(getattr(user, "role", "")).lower() == "admin"


def is_active_admin_user(user) -> bool:
    return isinstance(user, User) and user.active


def has_torquetrack_permission(user, permission: str | None) -> bool:
    if not is_active_admin_user(user):
        return False
    if is_full_access(user):
        return True
    if permission is None:
        return True
    role = get_staff_role(user)
    if role is not None:
        resolved = resolve_staff_permission(permission)
        if resolved is None:
            return False
        app_label, codename = resolved
        return role.permissions.filter(
            content_type__app_label=app_label, codename=codename
        ).exists()
    return permission in (user.permissions or [])


class HasTorqueTrackPermission(BasePermission):
    """Poner `required_permission` en la view. Sin eso, basta un User activo."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        required = getattr(view, "required_permission", None)
        return has_torquetrack_permission(user, required)
