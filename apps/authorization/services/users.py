"""Usuarios del panel: listar, cambiar `role`/`active` y borrar.

Nadie crea cuentas desde aquí: toda persona se registra como cliente
(`/api/register/`, en `apps.customers`) y después un admin le asigna un Role.

Reglas contra escalar privilegios (las de Role están en `roles.py`):

- nadie cambia su propio Role ni su propio estado, ni borra su cuenta;
- siempre queda al menos un usuario activo con acceso total.

Las reglas se evalúan dentro de `transaction.atomic` con las cuentas afectadas
bloqueadas (`lock_accounts`) y con el Role del actor releído de la base: dos
requests simultáneos no pueden validarse cada uno contra la foto vieja del
otro. `grants.py` reutiliza el bloqueo, la relectura y la regla del último
usuario con acceso total de este módulo.

Esta app está debajo de `apps.authentication`: el `User` se alcanza con
`get_user_model()`, nunca importándolo.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Case, IntegerField, Q, When

from apps.audit.services import record_activity
from apps.authorization.permissions import has_role_permission
from apps.authorization.services.roles import (
    has_full_access_role,
    is_full_access,
    permission_codenames_for_role,
    role_by_slug,
    role_grants_within,
    serialize_role,
    update_privilege_error,
)

_MISSING = object()
UPDATABLE_FIELDS = frozenset({"role", "active"})

FORBIDDEN = {"error": "Forbidden", "status": 403}
LAST_FULL_ACCESS = "At least one active full access user is required"


def _serialize_user(user, codenames_cache: dict | None = None) -> dict:
    role = user.role if user.role_id is not None else None
    if role is None:
        permissions = []
    elif codenames_cache is not None:
        if role.pk not in codenames_cache:
            codenames_cache[role.pk] = permission_codenames_for_role(role)
        permissions = codenames_cache[role.pk]
    else:
        permissions = permission_codenames_for_role(role)
    first_name, last_name = user.given_names()
    return {
        "id": user.pk,
        "email": user.email,
        "firstName": first_name,
        "lastName": last_name,
        "name": user.full_name(),
        "active": user.active,
        "isStaff": user.active and role is not None,
        "role": serialize_role(role) if role is not None else None,
        "permissions": permissions,
        "createdAt": user.created_at,
    }


def _parse_active(payload: dict):
    """`(valor, error)`. Un string `"false"` es truthy en Python: sin esta
    validación desactivar desde un form terminaría activando."""
    if "active" not in payload:
        return _MISSING, None
    value = payload["active"]
    if not isinstance(value, bool):
        return None, {"error": "active must be a boolean", "status": 400}
    return value, None


def _parse_role(payload: dict):
    """`(role | None | _MISSING, error)`. `role: null` quita el acceso al panel."""
    if "role" not in payload:
        return _MISSING, None
    raw = payload["role"]
    if raw is None:
        return None, None
    role = role_by_slug(raw)
    if role is None:
        return None, {"error": "Valid role required", "status": 400}
    return role, None


def log_user_activity(actor: str, action: str, user_id: str, data: dict) -> None:
    record_activity(
        actor=actor,
        action=action,
        entity_type="USER",
        entity_id=user_id,
        data=data,
    )


def lock_accounts(*user_ids: str) -> None:
    """Bloquea en una sola sentencia, ordenadas por pk, las cuentas de acceso
    total y las que se van a tocar.

    Bloquear siempre en el mismo orden evita el deadlock de dos admins que se
    editan uno al otro. Incluir a todas las de acceso total serializa la regla
    del último admin: el segundo request espera y la evalúa con lo que el
    primero ya confirmó. `of=("self",)` porque Postgres no bloquea el lado
    nullable del LEFT JOIN con `roles`.
    """
    User = get_user_model()
    list(
        User.objects.select_for_update(of=("self",))
        .filter(Q(role__full_access=True) | Q(pk__in=user_ids))
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def fresh_user(user_id: str):
    return get_user_model().objects.select_related("role").filter(pk=user_id).first()


def _fresh_manager(actor):
    """El actor releído con su fila bloqueada, o `None` si ya no puede
    gestionar usuarios (lo desactivaron o le cambiaron el Role en otro
    request)."""
    manager = fresh_user(actor.pk)
    if manager is None or not has_role_permission(manager, "users.manage"):
        return None
    return manager


def is_last_full_access_user(target) -> bool:
    return not get_user_model().objects.filter(
        active=True, role__full_access=True
    ).exclude(pk=target.pk).exists()


def list_admin_users() -> list[dict]:
    users = get_user_model().objects.select_related("role").order_by(
        Case(
            When(role__full_access=True, then=0),
            When(role__isnull=False, then=1),
            default=2,
            output_field=IntegerField(),
        ),
        "created_at",
    )
    cache: dict = {}
    return [_serialize_user(user, cache) for user in users]


def update_admin_user(user_id: str, payload: dict, actor) -> dict:
    """Solo `role` y `active`. Desactivar corta las sesiones en el request
    siguiente; un cambio de Role rige desde el request siguiente porque los
    permisos se leen en cada uno."""
    if not UPDATABLE_FIELDS.issuperset(payload):
        return {"error": "Only role and active can be changed", "status": 400}
    active, error = _parse_active(payload)
    if error is not None:
        return error
    new_role, error = _parse_role(payload)
    if error is not None:
        return error
    if user_id == actor.pk and (active is not _MISSING or new_role is not _MISSING):
        return {"error": "You cannot change your own role or active status", "status": 403}

    with transaction.atomic():
        lock_accounts(user_id, actor.pk)
        target = fresh_user(user_id)
        if target is None:
            return {"error": "User not found", "status": 404}
        manager = _fresh_manager(actor)
        if manager is None:
            return FORBIDDEN
        error = update_privilege_error(
            manager, target, None if new_role is _MISSING else new_role
        )
        if error is not None:
            return error

        if has_full_access_role(target):
            if active is False:
                return {"error": "A full access user must remain active", "status": 403}
            loses_full_access = new_role is not _MISSING and (
                new_role is None or not new_role.full_access
            )
            if loses_full_access and is_last_full_access_user(target):
                return {"error": LAST_FULL_ACCESS, "status": 403}

        if new_role is not _MISSING:
            target.role = new_role
        if active is not _MISSING:
            target.active = active
        target.save(update_fields=["role", "active"])

    log_user_activity(
        actor.email,
        "USER_UPDATED",
        target.pk,
        {
            "email": target.email,
            "role": target.role.slug if target.role_id else None,
            "active": target.active,
        },
    )
    return {"ok": True, "user": _serialize_user(target)}


def delete_admin_user(user_id: str, actor) -> dict:
    """El Customer vinculado se conserva (`SET_NULL`) para no perder el
    historial de pedidos."""
    if user_id == actor.pk:
        return {"error": "You cannot delete your own account", "status": 400}

    with transaction.atomic():
        lock_accounts(user_id, actor.pk)
        target = fresh_user(user_id)
        if target is None:
            return {"error": "User not found", "status": 404}
        manager = _fresh_manager(actor)
        if manager is None:
            return FORBIDDEN
        if has_full_access_role(target):
            return {"error": "A full access account cannot be deleted", "status": 403}
        if not is_full_access(manager) and not role_grants_within(target.role, manager.role):
            return {
                "error": "You cannot delete a user with permissions you do not have",
                "status": 403,
            }
        email = target.email
        target.delete()

    log_user_activity(actor.email, "USER_DELETED", user_id, {"email": email})
    return {"ok": True}
