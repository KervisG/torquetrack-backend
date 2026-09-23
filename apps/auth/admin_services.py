"""Alta, listado, edición y baja de usuarios del panel (`/api/admin/users/`).

El alta la hace solo quien tiene `users.manage`, con un Role explícito. En la
edición el Role no cambia: se reasigna en `/admin/` de Django.
"""
from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.db.models import Case, When
from django.utils import timezone

from apps.auth.models import EmployeeRole, User
from apps.auth.permissions import (
    assign_staff_role,
    attach_staff_roles,
    get_staff_role,
    is_full_access,
    legacy_role_label,
    permission_strings_for_role,
    role_from_payload,
    stored_permissions_for_role,
)
from apps.auth.services import compose_display_name, parse_email
from apps.auth.sessions import revoke_admin_sessions
from apps.backoffice.models import ActivityLog
from apps.checkout.services import random_id


def _serialize_user(user: User) -> dict:
    role = get_staff_role(user)
    first_name, last_name = user.given_names()
    payload = {
        "id": user.pk,
        "email": user.username,
        "firstName": first_name,
        "lastName": last_name,
        "name": user.full_name(),
        "username": user.username,
        "role": legacy_role_label(role) if role is not None else user.role,
        "active": user.active,
        "permissions": (
            permission_strings_for_role(role)
            if role is not None
            else (user.permissions or [])
        ),
        "createdAt": user.created_at,
    }
    if role is not None:
        payload["roleSlug"] = role.slug
    return payload


def list_admin_users() -> list[dict]:
    """`GET /api/admin/users/` — el rol admin primero, luego por `created_at`."""
    users = list(
        User.objects.order_by(
            Case(When(role="admin", then=0), default=1), "created_at"
        )
    )
    attach_staff_roles(users)
    return [_serialize_user(user) for user in users]


def create_admin_user(payload: dict, actor) -> dict:
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

    role = role_from_payload(payload.get("role"))
    if role is None:
        return {"error": "Valid role required", "status": 400}
    # `users.manage` no basta para crear un acceso total: sería escalar
    # privilegios por encima del propio Role.
    if role.full_access and not is_full_access(actor):
        return {"error": "Only a full access user can grant full access", "status": 403}

    user_id = random_id("U")
    display_name = compose_display_name(first_name, last_name)
    users_role = legacy_role_label(role)

    try:
        with transaction.atomic():
            user = User.objects.create(
                id=user_id,
                first_name=first_name,
                last_name=last_name,
                display_name=display_name,
                username=email,
                password_hash=make_password(str(password)),
                role=users_role,
                active=True,
                permissions=stored_permissions_for_role(role),
                created_at=timezone.now(),
            )
            assign_staff_role(user_id, role)
    except IntegrityError:
        return {"error": "Email already exists", "status": 409}

    ActivityLog.objects.create(
        actor_id=actor.username,
        action="USER_CREATED",
        entity_type="USER",
        entity_id=user_id,
        data={"email": email, "role": role.slug},
        created_at=timezone.now(),
    )
    user._staff_role = role
    return {"ok": True, "user": _serialize_user(user)}


def update_admin_user(user_id: str, payload: dict, actor_username: str) -> dict:
    """`PUT /api/admin/users/[id]/`.

    Quien tiene un Role de acceso total no se desactiva. El Role no se
    cambia aquí.
    """
    target = User.objects.filter(pk=user_id).first()
    if target is None:
        return {"error": "User not found", "status": 404}

    email = None
    if payload.get("email") is not None or payload.get("username") is not None:
        email = parse_email(payload.get("email") or payload.get("username"))
        if email is None:
            return {"error": "Valid email required", "status": 400}

    first_name = (
        str(payload.get("firstName")).strip()
        if payload.get("firstName") is not None
        else None
    )
    last_name = (
        str(payload.get("lastName")).strip()
        if payload.get("lastName") is not None
        else None
    )

    if is_full_access(target):
        if payload.get("active") is False:
            return {
                "error": "The primary Admin must remain active with full access",
                "status": 403,
            }

        if first_name is not None:
            target.first_name = first_name
        if last_name is not None:
            target.last_name = last_name
        if first_name is not None or last_name is not None:
            target.display_name = compose_display_name(
                (target.first_name or "").strip(),
                (target.last_name or "").strip(),
            )
        if email is not None:
            target.username = email
        if payload.get("password"):
            target.password_hash = make_password(str(payload["password"]))
        target.save(
            update_fields=[
                "first_name",
                "last_name",
                "display_name",
                "username",
                "password_hash",
            ]
        )
        permissions_for_log = ["*"]
    else:
        if first_name is not None:
            target.first_name = first_name
        if last_name is not None:
            target.last_name = last_name
        if first_name is not None or last_name is not None:
            target.display_name = compose_display_name(
                (target.first_name or "").strip(),
                (target.last_name or "").strip(),
            )
        if email is not None:
            target.username = email
        if payload.get("active") is not None:
            target.active = payload["active"]
        if payload.get("password"):
            target.password_hash = make_password(str(payload["password"]))
        target.save(
            update_fields=[
                "first_name",
                "last_name",
                "display_name",
                "username",
                "active",
                "password_hash",
            ]
        )
        current_role = get_staff_role(target)
        permissions_for_log = (
            stored_permissions_for_role(current_role)
            if current_role is not None
            else (target.permissions or [])
        )
        if payload.get("active") is False:
            revoke_admin_sessions(user_id)

    ActivityLog.objects.create(
        actor_id=actor_username,
        action="USER_UPDATED",
        entity_type="USER",
        entity_id=user_id,
        data={
            "email": email or target.username,
            "permissions": permissions_for_log,
        },
        created_at=timezone.now(),
    )
    return {"ok": True}


def delete_admin_user(user_id: str, actor_user_id: str, actor_username: str) -> dict:
    """`DELETE /api/admin/users/[id]/`."""
    if user_id == actor_user_id:
        return {"error": "You cannot delete your own account", "status": 400}

    target = User.objects.filter(pk=user_id).first()
    if target is None:
        return {"error": "User not found", "status": 404}

    if is_full_access(target):
        return {"error": "The primary Admin account cannot be deleted", "status": 403}

    email = target.username
    revoke_admin_sessions(user_id)
    EmployeeRole.objects.filter(user_id=user_id).delete()
    target.delete()
    ActivityLog.objects.create(
        actor_id=actor_username,
        action="USER_DELETED",
        entity_type="USER",
        entity_id=user_id,
        data={"email": email},
        created_at=timezone.now(),
    )
    return {"ok": True}
