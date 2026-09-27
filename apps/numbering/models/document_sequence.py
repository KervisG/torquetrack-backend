"""Series de numeración de documentos. Viven aparte de `checkout` porque las
usan pedidos y cotizaciones, y `apps/common` por diseño no tiene modelos."""
from django.db import models


class DocumentSequence(models.Model):
    """Una fila por serie (`order`, `quote`).

    `next_document_number` la bloquea con `select_for_update()`, así que dos
    requests concurrentes nunca leen el mismo `last_value`.
    """

    key = models.TextField(primary_key=True)
    last_value = models.PositiveBigIntegerField()

    class Meta:
        db_table = "document_sequences"
        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.key}:{self.last_value}"
