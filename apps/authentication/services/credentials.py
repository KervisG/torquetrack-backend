"""Credenciales del `User`: normalizar el email, validar y cambiar la
contraseña, y dar de alta la cuenta. El perfil `Customer` es de
`apps.customers`, que depende de esta app y no al revés."""
from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from apps.authentication.models import User, compose_display_name
from apps.authentication.services.tokens import invalidate_password_reset_tokens
from apps.common.ids import random_id

EMAIL_ALREADY_EXISTS = "Email already exists"


def parse_email(raw) -> str | None:
    email = str(raw or "").strip().lower()
    if not email:
        return None
    try:
        validate_email(email)
    except ValidationError:
        return None
    return email


def password_error(password: str, user: User) -> str | None:
    """Corre `AUTH_PASSWORD_VALIDATORS` y devuelve el mensaje, o `None`."""
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return " ".join(exc.messages)
    return None


def change_password(user: User, raw_password: str) -> None:
    """Única forma de cambiar una contraseña. El hash nuevo cambia el
    `get_session_auth_hash`, así que las sesiones abiertas con la anterior
    dejan de valer solas; los enlaces de reset pendientes se anulan aquí."""
    user.set_password(raw_password)
    user.save(update_fields=["password"])
    invalidate_password_reset_tokens(user.pk)


def create_account(
    *,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    display_name: str | None = None,
) -> dict:
    """Alta de una cuenta sin Role: toda persona entra como cliente y un
    admin le asigna el Role después (`/api/admin/users/<id>/` o
    `manage.py grant_role`). Devuelve `{"user": user}` o `{"error", "status"}`.
    Debe correr dentro de la transacción de quien lo llama si hay más filas que
    crear juntas."""
    candidate = User(
        id=random_id("U"),
        email=email,
        first_name=first_name,
        last_name=last_name,
        display_name=display_name or compose_display_name(first_name, last_name),
        active=True,
    )
    error = password_error(str(password), candidate)
    if error is not None:
        return {"error": error, "status": 400}
    # Se hashea antes de mirar si el email existe: así un email registrado
    # también paga el PBKDF2 y el tiempo de respuesta no revela la cuenta.
    candidate.set_password(str(password))
    if User.objects.filter(email=email).exists():
        return {"error": EMAIL_ALREADY_EXISTS, "status": 409}

    try:
        with transaction.atomic():
            candidate.save(force_insert=True)
    except IntegrityError:
        return {"error": EMAIL_ALREADY_EXISTS, "status": 409}
    return {"user": candidate}
