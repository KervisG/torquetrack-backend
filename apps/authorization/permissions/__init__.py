"""Permisos del panel: el catálogo (`catalog.py`) y la permission class de DRF
(`classes.py`). El Role es la única fuente de verdad.

Los helpers de Role (serializar, buscar por slug, comparar lo que concede)
viven en `services/roles.py`, que importa este paquete. El paquete no importa
`services/` ni modelos: lo usan todas las views para cablearse y
`tests/test_app_boundaries.py` exige que no dependa de nada más.
"""
from apps.authorization.permissions.catalog import (
    ALL_PERMISSION_CODENAMES,
    CODE_TO_PERMISSION,
    DEFAULT_EMPLOYEE_PERMISSIONS,
    PERMISSION_TO_CODE,
    STAFF_PERMISSIONS,
    resolve_staff_permission,
)
from apps.authorization.permissions.classes import (
    HasRolePermission,
    has_role_permission,
    is_staff_user,
)

__all__ = [
    "ALL_PERMISSION_CODENAMES",
    "CODE_TO_PERMISSION",
    "DEFAULT_EMPLOYEE_PERMISSIONS",
    "PERMISSION_TO_CODE",
    "STAFF_PERMISSIONS",
    "HasRolePermission",
    "has_role_permission",
    "is_staff_user",
    "resolve_staff_permission",
]
