"""Roles del panel: helpers de Role, el listado y las reglas contra escalar
privilegios.

Quien no tiene acceso total no asigna un Role que conceda algo que él no tiene
(el acceso total incluido) ni toca a un usuario cuyo Role lo tenga.

La dependencia va de aquí hacia `permissions.py` (el catálogo y
`is_staff_user`), nunca al revés: `permissions.py` es infraestructura de
request que no importa `services/`, así no hay ciclo.
"""
from __future__ import annotations

from django.contrib.auth.models import Permission
from django.db import transaction
from django.utils.text import slugify

from apps.audit.services import record_activity
from apps.authorization.models import Role
from apps.authorization.permissions import (
    ALL_PERMISSION_CODENAMES,
    CODE_TO_PERMISSION,
    PERMISSION_TO_CODE,
    has_role_permission,
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


def serialize_admin_role(role: Role) -> dict:
    return {
        "id": role.pk,
        **serialize_role(role),
        "permissions": permission_codenames_for_role(role),
    }


def role_by_slug(raw) -> Role | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Role.objects.filter(slug=raw.strip().lower()).first()


def list_admin_roles() -> list[dict]:
    roles = Role.objects.prefetch_related("permissions").order_by("-full_access", "name")
    return [serialize_admin_role(role) for role in roles]


def create_admin_role(payload: dict, actor) -> dict:
    """Crea un Role. El slug sale del nombre y no se puede cambiar después:
    las cuentas se asignan por slug."""
    parsed, error = _parse_role_body(payload)
    if error is not None:
        return error
    name, full_access, codes = parsed
    slug = slugify(name)
    if not slug:
        return {"error": "Role name must include a letter or number", "status": 400}

    with transaction.atomic():
        manager = _locked_manager(actor)
        if manager is None:
            return {"error": "Forbidden", "status": 403}
        error = _grant_error(manager, full_access, codes, current=None)
        if error is not None:
            return error
        if Role.objects.filter(slug=slug).exists() or Role.objects.filter(name=name).exists():
            return {"error": "A role with this name already exists", "status": 400}
        role = Role.objects.create(name=name, slug=slug, full_access=full_access)
        _set_permissions(role, [] if full_access else codes)
        record_activity(
            actor=manager.email,
            action="ROLE_CREATED",
            entity_type="ROLE",
            entity_id=str(role.pk),
            data={"slug": role.slug, "name": role.name, "fullAccess": role.full_access},
        )
    return serialize_admin_role(role)


def update_admin_role(slug: str, payload: dict, actor) -> dict:
    """Cambia nombre, acceso total y permisos. El slug queda: es el id que
    usa `PUT /api/admin/users/`."""
    parsed, error = _parse_role_body(payload)
    if error is not None:
        return error
    name, full_access, codes = parsed

    with transaction.atomic():
        manager = _locked_manager(actor)
        if manager is None:
            return {"error": "Forbidden", "status": 403}
        role = Role.objects.select_for_update().filter(slug=slug).first()
        if role is None:
            return {"error": "Role not found", "status": 404}
        error = _grant_error(manager, full_access, codes, current=role)
        if error is not None:
            return error
        if Role.objects.filter(name=name).exclude(pk=role.pk).exists():
            return {"error": "A role with this name already exists", "status": 400}
        # Quitar el acceso total al único Role que lo tiene deja la tienda
        # sin un admin activo, igual que quitarle el Role al último admin.
        if role.full_access and not full_access:
            if not Role.objects.filter(full_access=True).exclude(pk=role.pk).exists():
                return {
                    "error": "At least one active full access user is required",
                    "status": 403,
                }
        role.name = name
        role.full_access = full_access
        role.save(update_fields=["name", "full_access"])
        _set_permissions(role, [] if full_access else codes)
        record_activity(
            actor=manager.email,
            action="ROLE_UPDATED",
            entity_type="ROLE",
            entity_id=str(role.pk),
            data={"slug": role.slug, "name": role.name, "fullAccess": role.full_access},
        )
    return serialize_admin_role(role)


def _parse_role_body(payload) -> tuple[tuple[str, bool, list[str]], None] | tuple[None, dict]:
    if not isinstance(payload, dict):
        return None, {"error": "Role name is required", "status": 400}
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, {"error": "Role name is required", "status": 400}
    name = name.strip()
    if len(name) > 80:
        return None, {"error": "Role name must be 80 characters or fewer", "status": 400}
    full_access = payload.get("fullAccess", False)
    if not isinstance(full_access, bool):
        return None, {"error": "fullAccess must be a boolean", "status": 400}
    raw_permissions = payload.get("permissions", [])
    codes_are_strings = isinstance(raw_permissions, list) and all(
        isinstance(code, str) for code in raw_permissions
    )
    if not codes_are_strings:
        return None, {"error": "permissions must be a list of permission codes", "status": 400}
    unknown = [code for code in raw_permissions if code not in CODE_TO_PERMISSION]
    if unknown:
        return None, {"error": f"Unknown permission: {unknown[0]}", "status": 400}
    codes = list(dict.fromkeys(raw_permissions))
    return (name, full_access, codes), None


def _locked_manager(actor):
    """El actor releído con su fila bloqueada, o `None` si ya no puede
    gestionar roles."""
    from django.contrib.auth import get_user_model

    manager = (
        get_user_model()
        .objects.select_for_update(of=("self",))
        .select_related("role")
        .filter(pk=actor.pk)
        .first()
    )
    if manager is None or not has_role_permission(manager, "users.manage"):
        return None
    return manager


def _grant_error(manager, full_access: bool, codes: list[str], current: Role | None) -> dict | None:
    """Nadie reparte un Role con más de lo que él tiene, ni toca uno de
    acceso total si no lo tiene."""
    if is_full_access(manager):
        return None
    if full_access or (current is not None and current.full_access):
        return {"error": "Only a full access user can grant full access", "status": 403}
    held = set(permission_codenames_for_role(manager.role))
    extra = [code for code in codes if code not in held]
    if extra:
        return {"error": "You cannot grant permissions you do not have", "status": 403}
    return None


def _set_permissions(role: Role, codes: list[str]) -> None:
    if not codes:
        role.permissions.clear()
        return
    wanted = []
    for code in codes:
        app_label, codename = CODE_TO_PERMISSION[code]
        wanted.append(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    role.permissions.set(wanted)


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
