"""Permission class de DRF y los chequeos que usa.

Staff es un `User` activo con Role, y lo que puede hacer lo responde
`User.has_perm` (solo lee el Role) con el `Permission` que traduce el catálogo.
"""
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from apps.authorization.permissions.catalog import resolve_staff_permission


def is_staff_user(user) -> bool:
    """Staff del panel: cualquier Role. `user.is_staff` es otra cosa (solo el
    acceso total entra a `/django-admin/` de Django)."""
    return bool(getattr(user, "is_active", False) and getattr(user, "role_id", None))


def has_role_permission(user, code: str) -> bool:
    resolved = resolve_staff_permission(code)
    return resolved is not None and user.has_perm(".".join(resolved))


class HasRolePermission(BasePermission):
    """Poner `required_permission` en la view. Sin eso, basta ser staff."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            # DRF respondería `NotAuthenticated` ("Authentication credentials
            # were not provided."); el contrato de la API es un único 403 con
            # el mensaje de permiso, haya sesión o no.
            raise PermissionDenied()
        required = getattr(view, "required_permission", None)
        if required is None:
            return is_staff_user(request.user)
        return has_role_permission(request.user, required)
