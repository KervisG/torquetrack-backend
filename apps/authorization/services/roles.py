"""Roles del panel: helpers de Role, el listado y las reglas contra escalar
privilegios.

Quien no tiene acceso total no asigna un Role que conceda algo que él no tiene
(el acceso total incluido) ni toca a un usuario cuyo Role lo tenga.

La dependencia va de aquí hacia `permissions.py` (el catálogo y
`is_staff_user`), nunca al revés: `permissions.py` es infraestructura de
request que no importa `services/`, así no hay ciclo.
"""
from __future__ import annotations

from apps.authorization.models import Role
from apps.authorization.permissions import (
    ALL_PERMISSION_CODENAMES,
    PERMISSION_TO_CODE,
    is_staff_user,
)


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
    return [code for pair, code in PERMISSION_TO_CODE.items() if pair in pairs]


def role_permission_pairs(role: Role | None) -> frozenset[tuple[str, str]] | None:
    """`(app_label, codename)` que concede el Role. `None` significa acceso
    total (todo, incluidos los permisos que se agreguen mañana); sin Role es
    el conjunto vacío."""
    if role is None:
        return frozenset()
    if role.full_access:
        return None
    return frozenset(role.permissions.values_list("content_type__app_label", "codename"))


def role_grants_within(role: Role | None, actor_role: Role | None) -> bool:
    """`True` si todo lo que concede `role` también lo concede `actor_role`.
    Es la regla contra escalar privilegios: nadie reparte ni toca permisos
    que no tiene."""
    actor = role_permission_pairs(actor_role)
    if actor is None:
        return True
    granted = role_permission_pairs(role)
    return granted is not None and granted <= actor


def serialize_role(role: Role) -> dict:
    return {"slug": role.slug, "name": role.name, "fullAccess": role.full_access}


def role_by_slug(raw) -> Role | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Role.objects.filter(slug=raw.strip().lower()).first()


def list_admin_roles() -> list[dict]:
    return [
        {"id": role.pk, **serialize_role(role)}
        for role in Role.objects.order_by("-full_access", "name")
    ]


def has_full_access_role(user) -> bool:
    """Mira el Role aunque la cuenta esté inactiva: una cuenta de acceso
    total desactivada sigue sin poder tocarla quien no tiene acceso total."""
    return user.role_id is not None and user.role.full_access


def update_privilege_error(actor, target, new_role) -> dict | None:
    """Error 403 si `actor` no puede tocar a `target` o darle `new_role`.
    `new_role` en `None` significa que el Role no cambia o que se quita."""
    if is_full_access(actor):
        return None
    if has_full_access_role(target):
        return {
            "error": "Only a full access user can modify a full access user",
            "status": 403,
        }
    if not role_grants_within(target.role, actor.role):
        return {
            "error": "You cannot modify a user with permissions you do not have",
            "status": 403,
        }
    if new_role is None:
        return None
    if new_role.full_access:
        return {"error": "Only a full access user can grant full access", "status": 403}
    if not role_grants_within(new_role, actor.role):
        return {"error": "You cannot grant permissions you do not have", "status": 403}
    return None
