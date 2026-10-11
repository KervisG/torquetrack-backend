"""Usuarios y roles del panel, helpers de Role y `manage.py grant_role`. Un
módulo por tema; este `__init__` reexporta la API pública para que los imports
`from apps.authorization.services import ...` no dependan de la división.
`apps.authentication` toma de aquí `serialize_role` y
`permission_codenames_for_role` para la respuesta de sesión. Los tests
parchean el módulo donde se usa cada función
(`apps.authorization.services.users.record_activity`), no este."""
from apps.authorization.services.grants import NO_ROLE, grant_role
from apps.authorization.services.roles import (
    create_admin_role,
    list_admin_roles,
    permission_codenames_for_role,
    serialize_role,
    update_admin_role,
)
from apps.authorization.services.users import (
    delete_admin_user,
    list_admin_users,
    update_admin_user,
)

__all__ = [
    "NO_ROLE",
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
