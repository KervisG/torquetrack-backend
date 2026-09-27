"""Chequeo de la base para `GET /api/health/`, sin SQL propio."""
import logging

from django.db import DatabaseError, connection

logger = logging.getLogger(__name__)


def database_is_available() -> bool:
    """`ensure_connection` abre la conexión si no hay una; si ya había una
    (con `CONN_MAX_AGE`), `is_usable` confirma que sigue viva. El motivo del
    fallo va al log, nunca a la respuesta."""
    try:
        connection.ensure_connection()
        if not connection.is_usable():
            logger.warning("Health check: database connection is not usable")
            return False
    except DatabaseError as exc:
        logger.warning("Health check: database unavailable (%s)", type(exc).__name__)
        return False
    return True
