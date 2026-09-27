"""Login y forma del usuario de sesión que comparten las respuestas de
sesión, login, registro y activación.

La sesión es la de Django y no guarda nada propio del login. No hace falta
borrar filas de `django_session` al cambiar la contraseña, desactivar ni
cambiar el Role: `login()` guarda el hash de la contraseña en la sesión y un
cambio de contraseña invalida las demás; `ModelBackend.get_user` rechaza a un
usuario inactivo en el request siguiente, y los permisos se leen del Role en
cada request.
"""
from __future__ import annotations

from django.contrib.auth import authenticate
from django.middleware.csrf import get_token

from apps.authentication.models import User
from apps.authorization.permissions import is_staff_user
from apps.authorization.services import permission_codenames_for_role, serialize_role


def authenticate_user(request, email, password) -> User | None:
    """Clientes y staff entran por el mismo lado. Se pasan strings siempre:
    con `None`, `ModelBackend` sale antes de hashear la contraseña de relleno
    que iguala el tiempo de respuesta."""
    return authenticate(request, email=str(email or ""), password=str(password or ""))


def serialize_session_user(user: User) -> dict:
    """Forma compartida por las respuestas de sesión, login y registro."""
    first_name, last_name = user.given_names()
    role = user.role if user.role_id is not None else None
    return {
        "id": user.pk,
        "email": user.email,
        "firstName": first_name,
        "lastName": last_name,
        "isStaff": is_staff_user(user),
        "role": serialize_role(role) if role is not None else None,
        "permissions": permission_codenames_for_role(role),
        "emailVerified": user.email_verified_at is not None,
    }


def csrf_token_payload(request) -> dict:
    """Token CSRF para el body de la respuesta.

    El SPA lo guarda en memoria y lo manda en `X-CSRFToken`, así no tiene que
    leer la cookie, cuyo nombre cambia en producción (`__Host-csrftoken`).
    Después de `login()` devuelve el token ya rotado.
    """
    return {"csrfToken": get_token(request)}
