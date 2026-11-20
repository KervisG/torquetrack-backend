"""Roles del panel y la gestión de usuarios staff (`manage.py grant_role`
incluido). Este `__init__` reexporta la API pública; dentro del paquete cada
módulo importa del módulo concreto."""
from apps.roles.services.grants import grant_role
from apps.roles.services.roles import (
    create_admin_role,
    list_admin_roles,
    permission_codenames_for_role,
    serialize_role,
    update_admin_role,
)
from apps.roles.services.users import (
    delete_admin_user,
    list_admin_users,
    update_admin_user,
)

__all__ = [
    "create_admin_role",
    "delete_admin_user",
    "grant_role",
    "list_admin_roles",
    "list_admin_users",
    "permission_codenames_for_role",
    "serialize_role",
    "update_admin_role",
    "update_admin_user",
]
