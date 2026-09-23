"""Una sola sesión para clientes y staff: la de Django (`request.session`),
con la cookie `SESSION_COOKIE_NAME`.

La sesión solo guarda el id del `User`. Lo que la persona puede hacer se
decide en cada request contra su Role, así que ascender o degradar a
alguien no depende de lo que tenga guardado su cookie.
"""
from django.contrib.sessions.models import Session
from django.middleware.csrf import get_token, rotate_token
from django.utils import timezone

SESSION_USER_KEY = "user_id"


def start_user_session(request, user) -> None:
    """Inicia sesión como `user` en el request actual.

    `flush()` descarta la session key que el cliente ya traía, para que un
    token fijado de antemano por un tercero no quede promovido a sesión
    autenticada. El token CSRF también rota, igual que en `django.contrib.auth.login`.
    """
    request.session.flush()
    request.session[SESSION_USER_KEY] = user.pk
    rotate_token(request)


def csrf_token_payload(request) -> dict:
    """Token CSRF para el body de la respuesta.

    El SPA lo guarda en memoria y lo manda en `X-CSRFToken`, así no tiene que
    leer la cookie, cuyo nombre cambia en producción (`__Host-csrftoken`).
    Después de `start_user_session` devuelve el token ya rotado.
    """
    return {"csrfToken": get_token(request)}


def end_user_session(request) -> None:
    request.session.flush()


def revoke_user_sessions(user_id: str) -> None:
    """Borra todas las sesiones vivas de `user_id`.

    Se llama al desactivar, borrar, cambiar la contraseña o cambiar el Role
    de un usuario. La autenticación ya revalida `active` en cada request;
    borrar las filas evita que una reactivación resucite sesiones viejas y
    que una contraseña filtrada siga sirviendo después del cambio.

    Recorre las sesiones vivas en vez de filtrar en SQL porque
    `session_data` es un blob firmado, no columnas consultables. Solo corre
    en esas operaciones administrativas, no en cada request.
    """
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        if session.get_decoded().get(SESSION_USER_KEY) == user_id:
            session.delete()
