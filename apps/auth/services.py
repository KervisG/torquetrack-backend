"""Reglas de autenticación del panel: verificar credenciales y describir al
empleado que está detrás de una sesión.

Port de `app/api/admin/login/route.ts` y `app/api/admin/session/route.ts`.
El alta y la edición de empleados no viven acá: eso es `apps/accounts/`.
"""
from __future__ import annotations

from django.contrib.auth.hashers import check_password

from apps.accounts.models import User


def authenticate_admin_user(username, password) -> User | None:
    """`POST /api/admin/login` — port de `app/api/admin/login/route.ts`.

    Devuelve `None` tanto para usuario inexistente como para password
    incorrecto: el original responde el mismo 401 en ambos casos y no
    conviene distinguirlos hacia afuera.
    """
    user = User.objects.filter(username__iexact=str(username or ""), active=True).first()
    if user is None:
        return None

    # A propósito NO se pasa `setter=` a `check_password`: `ScryptLegacyHasher.
    # must_update` devuelve siempre True, así que un setter rehashearía la fila
    # a PBKDF2 y `verifyPassword` de `lib/auth.ts` (que rechaza todo algoritmo
    # que no sea `scrypt`) dejaría a ese empleado fuera del admin de Next.js
    # que sigue en producción. El rehash recién es seguro cuando Next.js no
    # valide más passwords.
    try:
        matches = check_password(str(password or ""), user.password_hash)
    except ValueError:
        # Hash vacío o con un algoritmo desconocido: `identify_hasher` explota,
        # mientras que el `try/catch` de `verifyPassword` lo trata como fallo.
        return None

    return user if matches else None


def serialize_admin_session_user(user: User) -> dict:
    """`GET /api/admin/session` — el rol `admin` reporta `["*"]` en lugar de
    su jsonb, igual que `app/api/admin/session/route.ts`."""
    is_admin = str(user.role).lower() == "admin"
    return {
        "id": user.pk,
        "username": user.username,
        "name": user.display_name or user.username,
        "role": user.role,
        "permissions": ["*"] if is_admin else (user.permissions or []),
    }
