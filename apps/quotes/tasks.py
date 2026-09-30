"""Tareas de Celery de cotizaciones. Beat las programa (`CELERY_BEAT_SCHEDULE`);
`manage.py expire_quotes` sigue sirviendo para correrlas a mano."""
import logging

from celery import shared_task

from apps.quotes.services import expire_stale_quotes

logger = logging.getLogger(__name__)


@shared_task(name="apps.quotes.tasks.expire_quotes")
def expire_quotes() -> int:
    # Idempotente: con `acks_late` un reintento tras la caída del worker solo
    # vuelve a marcar lo que ya venció.
    expired = expire_stale_quotes()
    logger.info("Expired %s stale quote(s)", expired)
    return expired
