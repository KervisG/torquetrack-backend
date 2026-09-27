"""Asignar un Role desde la terminal (`manage.py grant_role`).

Es la puerta de entrada cuando todavía no hay nadie con `users.manage`. Usa el
mismo bloqueo y la misma regla del último usuario activo con acceso total que
el panel (`users.py`).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from apps.authorization.services.roles import has_full_access_role, role_by_slug
from apps.authorization.services.users import (
    LAST_FULL_ACCESS,
    fresh_user,
    is_last_full_access_user,
    lock_accounts,
    log_user_activity,
)

# Valor de `manage.py grant_role --role` que quita el Role.
NO_ROLE = "none"
# Actor de la bitácora para los cambios hechos desde la terminal.
COMMAND_ACTOR = "manage.py grant_role"


def grant_role(email, role_slug) -> tuple[dict, int]:
    """Asigna (o quita con `none`) el Role de una cuenta YA registrada.

    No pide actor y nunca crea la cuenta; la persona se registra antes en la
    tienda (o con `createsuperuser` en desarrollo). No toca la contraseña ni
    `active`. Mantiene la regla del último usuario activo con acceso total.
    """
    normalized = str(email or "").strip().lower()
    try:
        validate_email(normalized)
    except ValidationError:
        return {"error": "A valid --email is required."}, 400

    slug = str(role_slug or "").strip().lower()
    if slug == NO_ROLE:
        role = None
    else:
        role = role_by_slug(slug)
        if role is None:
            return {"error": f"Unknown role: {slug}"}, 400

    User = get_user_model()
    with transaction.atomic():
        pk = User.objects.filter(email=normalized).values_list("pk", flat=True).first()
        if pk is None:
            return {
                "error": "No account with that email; sign up in the store first."
            }, 404
        lock_accounts(pk)
        user = fresh_user(pk)
        loses_full_access = role is None or not role.full_access
        if (
            has_full_access_role(user)
            and user.active
            and loses_full_access
            and is_last_full_access_user(user)
        ):
            return {"error": LAST_FULL_ACCESS}, 409
        user.role = role
        user.save(update_fields=["role"])

    log_user_activity(
        COMMAND_ACTOR, "USER_ROLE_GRANTED", user.pk, {"email": user.email, "role": slug}
    )
    return {"user": user, "role": role}, 200
