"""Números correlativos (`O<n>`, `Q<n>`). Es una app hoja: no importa ninguna
app de dominio."""
from django.db import transaction

from apps.numbering.models import DocumentSequence

FIRST_DOCUMENT_NUMBER = 10001


def next_document_number(key: str, prefix: str) -> str:
    """El bloqueo de la fila hace esperar a cada llamada concurrente, así que
    nunca se emite dos veces el mismo número. Si dos crean la fila a la vez,
    `get_or_create` reintenta la lectura bloqueante."""
    with transaction.atomic():
        sequence, created = DocumentSequence.objects.select_for_update().get_or_create(
            key=key, defaults={"last_value": FIRST_DOCUMENT_NUMBER}
        )
        if not created:
            sequence.last_value += 1
            sequence.save(update_fields=["last_value"])
    return f"{prefix}{sequence.last_value}"
