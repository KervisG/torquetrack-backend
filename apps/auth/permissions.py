"""Permisos del panel. El Role es la única fuente de verdad: staff es un
`User` activo con Role, y lo que puede hacer sale de `role.full_access` o
de los `Permission` del Role, colgados de los modelos de dominio.
"""
from rest_framework.permissions import BasePermission

from apps.auth.models import Role, User
from apps.auth.permission_catalog import (
    DJANGO_TO_LEGACY,
    STAFF_PERMISSIONS,
    resolve_staff_permission,
)

ALL_PERMISSION_CODENAMES = [legacy for legacy, *_rest in STAFF_PERMISSIONS]


def is_staff_user(user) -> bool:
    return isinstance(user, User) and user.active and user.role_id is not None


def is_full_access(user) -> bool:
    return is_staff_user(user) and user.role.full_access


def permission_codenames_for_role(role: Role | None) -> list[str]:
    """Strings del catálogo (`orders.view`) que concede el Role.

    Un Role de acceso total concede el catálogo completo; así el cliente no
    necesita un comodín para saber qué mostrar.
    """
    if role is None:
        return []
    if role.full_access:
        return list(ALL_PERMISSION_CODENAMES)
    pairs = set(role.permissions.values_list("content_type__app_label", "codename"))
    return [
        DJANGO_TO_LEGACY[pair]
        for pair in DJANGO_TO_LEGACY
        if pair in pairs
    ]


def has_torquetrack_permission(user, permission: str | None) -> bool:
    if not is_staff_user(user):
        return False
    role = user.role
    if role.full_access:
        return True
    if permission is None:
        return True
    resolved = resolve_staff_permission(permission)
    if resolved is None:
        return False
    app_label, codename = resolved
    return role.permissions.filter(
        content_type__app_label=app_label, codename=codename
    ).exists()


def role_by_slug(raw) -> Role | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Role.objects.filter(slug=raw.strip().lower()).first()


class HasTorqueTrackPermission(BasePermission):
    """Poner `required_permission` en la view. Sin eso, basta ser staff."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        required = getattr(view, "required_permission", None)
        return has_torquetrack_permission(user, required)
