"""Credenciales y sesión del panel."""
from __future__ import annotations

from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from apps.auth.models import User
from apps.auth.permissions import (
    get_staff_role,
    legacy_role_label,
    permission_strings_for_role,
)


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
