"""Trabajo fuera del request, sin worker asíncrono.

Lo usan los correos de cuenta: llamar a Resend dentro del request hace que
`POST /api/password-reset/` tarde más cuando la cuenta existe, y ese tiempo
revela qué correos están registrados. Un hilo daemon alcanza porque el
trabajo es corto y no necesita reintentos; si el proceso se cae a mitad de
un envío, ese correo se pierde y la persona lo vuelve a pedir.
"""
import logging
import threading

from django.db import connections

logger = logging.getLogger(__name__)


def run_in_background(func, *args, **kwargs) -> threading.Thread:
    """Corre `func(*args, **kwargs)` en un hilo daemon y devuelve el hilo.

    Una excepción no tiene a quién llegar, así que se registra con su
    traceback. Si `func` abrió conexiones a la base, se cierran al terminar:
    Django las abre por hilo y nadie más las cerraría.
    """

    def _target():
        try:
            func(*args, **kwargs)
        except Exception:
            logger.exception("Background task %s failed", getattr(func, "__qualname__", func))
        finally:
            connections.close_all()

    thread = threading.Thread(target=_target, name="torquetrack-background", daemon=True)
    thread.start()
    return thread
