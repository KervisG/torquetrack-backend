"""Usuarios y roles del panel (`/api/admin/users/`, `/api/admin/roles/`).

Solo quien tiene `users.manage` llega aquí. El Role se identifica por
`slug`. Dos reglas evitan escalar privilegios por encima del propio Role:
nadie sin acceso total concede acceso total, ni edita a quien lo tiene.
"""
from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.db.models import Case, IntegerField, When
from django.utils import timezone

from apps.auth.models import Role, User
from apps.auth.permissions import (
    is_full_access,
    permission_codenames_for_role,
    role_by_slug,
)
from apps.auth.services import (
    compose_display_name,
    create_account,
    parse_email,
    password_error,
    serialize_role,
)
from apps.auth.sessions import revoke_user_sessions
from apps.backoffice.models import ActivityLog

_MISSING = object()


def _serialize_user(user: User, codenames_cache: dict | None = None) -> dict:
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


def _log(actor: User, action: str, user_id: str, data: dict) -> None:
    ActivityLog.objects.create(
        actor_id=actor.email,
        action=action,
        entity_type="USER",
        entity_id=user_id,
        data=data,
        created_at=timezone.now(),
    )


def list_admin_roles() -> list[dict]:
    """`GET /api/admin/roles/`."""
    return [
        {"id": role.pk, **serialize_role(role)}
        for role in Role.objects.order_by("-full_access", "name")
    ]


def list_admin_users() -> list[dict]:
    """`GET /api/admin/users/` — acceso total, luego staff, luego clientes."""
    users = User.objects.select_related("role").order_by(
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


def create_admin_user(payload: dict, actor: User) -> dict:
    """`POST /api/admin/users/` — correo, contraseña, nombre, apellidos y Role.

    El id lo genera el servidor; un `id` en el body se ignora.
    """
    email = parse_email(payload.get("email"))
    password = payload.get("password")
    first_name = str(payload.get("firstName") or "").strip()
    last_name = str(payload.get("lastName") or "").strip()
    if email is None or not password or not first_name or not last_name:
        return {
            "error": "Email, password, first name and last name required",
            "status": 400,
        }

    role, error = _parse_role(payload)
    if error is not None or role is None or role is _MISSING:
        return {"error": "Valid role required", "status": 400}
    if role.full_access and not is_full_access(actor):
        return {"error": "Only a full access user can grant full access", "status": 403}

    active, error = _parse_active(payload)
    if error is not None:
        return error

    with transaction.atomic():
        result = create_account(
            email=email,
            password=str(password),
            first_name=first_name,
            last_name=last_name,
            role=role,
        )
        if "error" in result:
            return result
        user = result["user"]
        if active is False:
            user.active = False
            user.save(update_fields=["active"])

    _log(actor, "USER_CREATED", user.pk, {"email": email, "role": role.slug})
    return {"ok": True, "user": _serialize_user(user)}


def _has_full_access_role(user: User) -> bool:
    """Mira el Role aunque la cuenta esté inactiva: una cuenta de acceso
    total desactivada sigue sin poder tocarla quien no tiene acceso total."""
    return user.role_id is not None and user.role.full_access


def _is_last_full_access_user(target: User) -> bool:
    return not User.objects.filter(
        active=True, role__full_access=True
    ).exclude(pk=target.pk).exists()


def update_admin_user(user_id: str, payload: dict, actor: User) -> dict:
    """`PUT /api/admin/users/[id]/` — email, nombres, contraseña, `active` y
    `role` (slug, o `null` para quitar el acceso al panel).

    Cambiar el Role, la contraseña o desactivar corta sus sesiones vivas.
    """
    target = User.objects.select_related("role").filter(pk=user_id).first()
    if target is None:
        return {"error": "User not found", "status": 404}

    target_full_access = _has_full_access_role(target)
    if target_full_access and not is_full_access(actor):
        return {
            "error": "Only a full access user can modify a full access user",
            "status": 403,
        }

    active, error = _parse_active(payload)
    if error is not None:
        return error
    new_role, error = _parse_role(payload)
    if error is not None:
        return error

    if new_role is not _MISSING and new_role is not None and new_role.full_access:
        if not is_full_access(actor):
            return {"error": "Only a full access user can grant full access", "status": 403}

    if target_full_access:
        if active is False:
            return {"error": "A full access user must remain active", "status": 403}
        loses_full_access = new_role is not _MISSING and (
            new_role is None or not new_role.full_access
        )
        if loses_full_access and _is_last_full_access_user(target):
            return {
                "error": "At least one active full access user is required",
                "status": 403,
            }

    email = None
    if payload.get("email") is not None:
        email = parse_email(payload.get("email"))
        if email is None:
            return {"error": "Valid email required", "status": 400}
        if User.objects.filter(email=email).exclude(pk=target.pk).exists():
            return {"error": "Email already exists", "status": 409}

    password = payload.get("password")
    if password:
        error_message = password_error(str(password), target)
        if error_message is not None:
            return {"error": error_message, "status": 400}

    if payload.get("firstName") is not None:
        target.first_name = str(payload["firstName"]).strip()
    if payload.get("lastName") is not None:
        target.last_name = str(payload["lastName"]).strip()
    target.display_name = compose_display_name(
        (target.first_name or "").strip(), (target.last_name or "").strip()
    )
    if email is not None:
        target.email = email

    previous_role_id = target.role_id
    if new_role is not _MISSING:
        target.role = new_role
    role_changed = target.role_id != previous_role_id

    was_active = target.active
    if active is not _MISSING:
        target.active = active
    if password:
        target.password_hash = make_password(str(password))

    try:
        with transaction.atomic():
            target.save()
    except IntegrityError:
        return {"error": "Email already exists", "status": 409}

    deactivated = was_active and not target.active
    if deactivated or role_changed or password:
        revoke_user_sessions(target.pk)

    _log(
        actor,
        "USER_UPDATED",
        target.pk,
        {
            "email": target.email,
            "role": target.role.slug if target.role_id else None,
            "active": target.active,
        },
    )
    return {"ok": True, "user": _serialize_user(target)}


def delete_admin_user(user_id: str, actor: User) -> dict:
    """`DELETE /api/admin/users/[id]/`. El Customer vinculado se conserva
    (`on_delete=SET_NULL`) para no perder el historial de pedidos."""
    if user_id == actor.pk:
        return {"error": "You cannot delete your own account", "status": 400}

    target = User.objects.select_related("role").filter(pk=user_id).first()
    if target is None:
        return {"error": "User not found", "status": 404}

    if _has_full_access_role(target):
        return {"error": "A full access account cannot be deleted", "status": 403}

    email = target.email
    revoke_user_sessions(user_id)
    target.delete()
    _log(actor, "USER_DELETED", user_id, {"email": email})
    return {"ok": True}
