"""Tareas de Celery del checkout. Beat las programa (`CELERY_BEAT_SCHEDULE`)."""
import logging

from celery import shared_task

from apps.checkout.services import expire_stale_payments

logger = logging.getLogger(__name__)


@shared_task(name="apps.checkout.tasks.expire_pending_payments")
def expire_pending_payments() -> int:
    """Reemplaza el evento `checkout.session.expired` de Stripe: Authorize.net
    no avisa cuando un cliente abandona el formulario. Idempotente: un
    reintento solo vuelve a mirar pagos que ya no están PENDING."""
    cancelled = expire_stale_payments()
    logger.info("Expired pending payments; cancelled %s order(s)", cancelled)
    return cancelled
