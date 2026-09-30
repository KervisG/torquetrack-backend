"""Handler de `logging` que avisa por correo al operador de cada error del servidor.

Cuelga del root en `LOGGING` (junto a la consola), así cubre los 500 que loguea
`django.request` y todo `logger.error`/`logger.exception` de las apps. Sin
`ERROR_ALERT_EMAILS` no hace nada (local y tests).

Vive en `config/` y no en una app, igual que `exceptions.py`: es cableado del
framework que referencia `settings`, no regla de un dominio. `apps/common/`
solo tiene helpers sin estado ni I/O, y `apps/integrations/` solo adaptadores
sin políticas; el límite de envíos es una política, así que el correo sale del
adaptador de Resend (`resend.send_email`) como en cualquier service.

Reglas que no se deducen del código:

- Un correo por firma (logger + tipo de excepción + archivo:línea del frame
  más interno, o el template del mensaje si no hay excepción) cada 15 minutos.
  El límite vive en el cache compartido para valer entre workers de gunicorn;
  si el cache falla (la base caída es justo cuando se disparan los errores) se
  usa un respaldo en memoria del proceso y se intenta mandar igual.
- `emit` nunca lanza: un handler que falla no puede romper el request.
- Un flag por hilo y la lista de loggers ignorados evitan que un fallo de
  Resend (o un error logueado mientras se manda) dispare otra alerta.
"""
from __future__ import annotations

import hashlib
import logging
import sys
import threading
import time
from datetime import UTC, datetime

from django.conf import settings
from django.core.cache import cache

from apps.integrations.email import resend

ALERT_WINDOW_SECONDS = 15 * 60
SEND_TIMEOUT_SECONDS = 5
SUBJECT_MAX_LENGTH = 120
CACHE_KEY_PREFIX = "error-alert:"
# Los bots mandan Host falsos todo el tiempo: avisar de cada uno sería ruido.
# Los loggers del adaptador y de este módulo se ignoran para no alertar sobre
# el propio envío de la alerta.
IGNORED_LOGGERS = (
    "django.security.DisallowedHost",
    "apps.integrations.email",
    __name__,
)
# Tope del respaldo en memoria: sin cache, cada firma nueva suma una entrada.
LOCAL_MAX_ENTRIES = 1000

_local_last_sent: dict[str, float] = {}
_local_lock = threading.Lock()
_reentrancy = threading.local()


class ErrorEmailHandler(logging.Handler):
    def __init__(self, level=logging.ERROR):
        super().__init__(level=level)

    def emit(self, record):
        if getattr(_reentrancy, "active", False):
            return
        _reentrancy.active = True
        try:
            self._emit(record)
        except Exception as exc:  # noqa: BLE001 - un handler nunca rompe el request
            _report_failure(exc)
        finally:
            _reentrancy.active = False

    def _emit(self, record):
        recipients = list(getattr(settings, "ERROR_ALERT_EMAILS", None) or [])
        if not recipients or record.levelno < logging.ERROR or _is_ignored(record.name):
            return
        if not _should_send(error_signature(record)):
            return
        resend.send_email(
            to=recipients,
            subject=alert_subject(record),
            text=alert_body(record),
            timeout=SEND_TIMEOUT_SECONDS,
        )


def _is_ignored(logger_name: str) -> bool:
    return any(
        logger_name == name or logger_name.startswith(f"{name}.") for name in IGNORED_LOGGERS
    )


def error_signature(record) -> str:
    """El mismo error repetido comparte firma aunque cambien los argumentos."""
    exc_info = record.exc_info
    if exc_info and exc_info[0] is not None:
        location = ""
        traceback = exc_info[2]
        if traceback is not None:
            while traceback.tb_next is not None:
                traceback = traceback.tb_next
            location = f"{traceback.tb_frame.f_code.co_filename}:{traceback.tb_lineno}"
        return f"{record.name}|{exc_info[0].__module__}.{exc_info[0].__qualname__}|{location}"
    return f"{record.name}|{record.msg}"


def _should_send(signature: str) -> bool:
    key = CACHE_KEY_PREFIX + hashlib.sha256(signature.encode("utf-8")).hexdigest()
    try:
        # `add` solo escribe si la clave no existe: es atómico entre workers.
        return bool(cache.add(key, 1, ALERT_WINDOW_SECONDS))
    except Exception:  # noqa: BLE001 - cache caído: se limita en memoria
        return _should_send_locally(key)


def _should_send_locally(key: str) -> bool:
    now = time.monotonic()
    with _local_lock:
        last = _local_last_sent.get(key)
        if last is not None and now - last < ALERT_WINDOW_SECONDS:
            return False
        if len(_local_last_sent) >= LOCAL_MAX_ENTRIES:
            expired = [k for k, t in _local_last_sent.items() if now - t >= ALERT_WINDOW_SECONDS]
            for stale in expired:
                del _local_last_sent[stale]
        _local_last_sent[key] = now
        return True


def _safe_message(record) -> str:
    try:
        return record.getMessage()
    except Exception:  # noqa: BLE001 - argumentos que no encajan con el template
        return str(record.msg)


def alert_subject(record) -> str:
    message = " ".join(_safe_message(record).split())
    subject = f"[TorqueTrack] {record.levelname} {record.name}: {message}"
    if len(subject) > SUBJECT_MAX_LENGTH:
        subject = subject[: SUBJECT_MAX_LENGTH - 3].rstrip() + "..."
    return subject


def alert_body(record) -> str:
    # Del request solo van el método, el path SIN query string y el id del
    # usuario. Nunca el body, los headers, las cookies ni la query (tokens de
    # enlaces por correo, emails): el correo sale del servidor y no puede
    # llevar credenciales ni datos personales.
    timestamp = datetime.fromtimestamp(record.created, tz=UTC)
    lines = [
        f"Time: {timestamp:%Y-%m-%d %H:%M:%S} UTC",
        f"Level: {record.levelname}",
        f"Logger: {record.name}",
        f"Message: {_safe_message(record)}",
    ]
    request = getattr(record, "request", None)
    if request is not None:
        lines.append(f"Request: {getattr(request, 'method', '?')} {getattr(request, 'path', '?')}")
        lines.append(f"User: {_user_id(request)}")
    if record.exc_info:
        lines += ["", logging.Formatter().formatException(record.exc_info)]
    if record.stack_info:
        lines += ["", record.stack_info]
    return "\n".join(lines) + "\n"


def _user_id(request) -> str:
    try:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return str(user.pk)
    except Exception:  # noqa: BLE001 - leer la sesión puede fallar con la base caída
        return "unknown"
    return "anonymous"


def _report_failure(exc: Exception) -> None:
    """Una sola línea a stderr en vez del traceback de `Handler.handleError`."""
    try:
        sys.stderr.write(f"Error alert email failed: {type(exc).__name__}\n")
    except Exception:  # noqa: BLE001
        pass
