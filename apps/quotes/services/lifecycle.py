"""Ciclo de vida de una cotización: número, token del enlace público y
vencimiento. Lo usan el storefront, el panel y `manage.py expire_quotes`."""
from __future__ import annotations

import secrets

from django.db.models import Q
from django.utils import timezone

from apps.numbering.services import next_document_number
from apps.quotes.models import Quote


def quote_token() -> str:
    return secrets.token_hex(24)


def next_quote_number() -> str:
    return next_document_number("quote", "Q")


def is_expired(quote: Quote) -> bool:
    return bool(quote.expires_at and quote.expires_at < timezone.now())


# Estados abiertos que el vencimiento convierte en `EXPIRED`; los cerrados
# (`CONVERTED`, `LOST`...) conservan el suyo.
EXPIRABLE_QUOTE_STATUSES = ("BUILDING", "ACTIVE", "CONTACTED")


def effective_quote_status(quote: Quote) -> str:
    """El vencimiento se calcula al leer: ningún GET persiste `EXPIRED`."""
    if quote.status in EXPIRABLE_QUOTE_STATUSES and is_expired(quote):
        return "EXPIRED"
    return quote.status


def unexpired_quotes_q() -> Q:
    return Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())


def expire_stale_quotes() -> int:
    return Quote.objects.filter(
        status__in=EXPIRABLE_QUOTE_STATUSES, expires_at__lt=timezone.now()
    ).update(status="EXPIRED", updated_at=timezone.now())
