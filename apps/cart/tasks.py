"""Tareas de Celery del carrito. Beat las programa (`CELERY_BEAT_SCHEDULE`);
`manage.py purge_carts` sigue sirviendo para correrlas a mano."""
import logging

from celery import shared_task

from apps.cart.services import purge_empty_carts, send_abandoned_cart_emails

logger = logging.getLogger(__name__)


@shared_task(name="apps.cart.tasks.purge_carts")
def purge_carts() -> int:
    # Idempotente: con `acks_late` un reintento tras la caída del worker no
    # borra nada de más.
    deleted = purge_empty_carts()
    logger.info("Purged %s empty cart(s)", deleted)
    return deleted


@shared_task(name="apps.cart.tasks.send_cart_recovery_emails")
def send_cart_recovery_emails() -> int:
    # Idempotente: la marca por carrito impide un segundo correo si la tarea
    # se reintenta tras la caída del worker.
    sent = send_abandoned_cart_emails()
    logger.info("Sent %s cart recovery email(s)", sent)
    return sent
