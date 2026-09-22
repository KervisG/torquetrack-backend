"""Credenciales, sesión y registro general.

El rol de un alta lo asigna el sistema. Quien registra no elige Role.
"""
from __future__ import annotations

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.auth.models import User
from apps.auth.permissions import (
    assign_staff_role,
    default_system_role,
    get_staff_role,
    legacy_role_label,
    permission_strings_for_role,
    stored_permissions_for_role,
)
from apps.backoffice.models import ActivityLog


def compose_display_name(first_name: str, last_name: str) -> str:
    return " ".join(part for part in (first_name, last_name) if part)


def parse_email(raw) -> str | None:
    email = str(raw or "").strip().lower()
    if not email:
        return None
    try:
        validate_email(email)
    except ValidationError:
        return None
    return email


def authenticate_admin_user(email, password) -> User | None:
    """`POST /api/admin/login/`."""
    user = User.objects.filter(username__iexact=str(email or ""), active=True).first()
    if user is None:
        return None

    # `ScryptLegacyHasher.must_update` es siempre True. Un `setter=`
    # reescribiría el hash y rompería filas que aún se verifican como scrypt.
    try:
        matches = check_password(str(password or ""), user.password_hash)
    except ValueError:
        return None

    return user if matches else None


def serialize_admin_session_user(user: User) -> dict:
    """`GET /api/admin/session/` — el rol Admin reporta `["*"]`."""
    role = get_staff_role(user)
    first_name, last_name = user.given_names()
    permissions = (
        permission_strings_for_role(role)
        if role is not None
        else (["*"] if str(user.role).lower() == "admin" else (user.permissions or []))
    )
    return {
        "id": user.pk,
        "email": user.username,
        "username": user.username,
        "firstName": first_name,
        "lastName": last_name,
        "name": user.full_name(),
        "role": legacy_role_label(role) if role is not None else user.role,
        "permissions": permissions,
    }


def register_user(payload: dict) -> dict:
    """`POST /api/register/` — correo, contraseña, nombre y apellidos."""
    email = parse_email(payload.get("email"))
    password = payload.get("password")
    first_name = str(payload.get("firstName") or "").strip()
    last_name = str(payload.get("lastName") or "").strip()
    if email is None or not password or not first_name or not last_name:
        return {
            "error": "Email, password, first name and last name required",
            "status": 400,
        }

    role = default_system_role()
    if role is None:
        return {"error": "Registration is not configured", "status": 503}

    user_id = payload.get("id") or _random_id("U")
    display_name = compose_display_name(first_name, last_name)
    permissions = stored_permissions_for_role(role)
    users_role = legacy_role_label(role)

    try:
        with transaction.atomic():
            User.objects.create(
                id=user_id,
                first_name=first_name,
                last_name=last_name,
                display_name=display_name,
                username=email,
                password_hash=make_password(str(password)),
                role=users_role,
                active=True,
                permissions=permissions,
                created_at=timezone.now(),
            )
            assign_staff_role(user_id, role)
    except IntegrityError:
        return {"error": "Email already exists", "status": 409}

    ActivityLog.objects.create(
        actor_id=email,
        action="USER_CREATED",
        entity_type="USER",
        entity_id=user_id,
        data={"email": email, "role": role.slug},
        created_at=timezone.now(),
    )
    return {
        "ok": True,
        "user": {
            "id": user_id,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "name": display_name,
            "username": email,
            "role": users_role,
            "roleSlug": role.slug,
            "active": True,
            "permissions": permissions,
        },
    }


def _random_id(prefix: str) -> str:
    from apps.checkout.services import random_id

    return random_id(prefix)
