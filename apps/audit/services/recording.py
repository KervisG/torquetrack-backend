"""`audit` es una dependencia hoja: no importa nada de pedidos, cotizaciones ni
clientes, así cualquier app puede registrar actividad sin crear ciclos."""
from __future__ import annotations

from apps.audit.models import ActivityLog


def record_activity(
    actor: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    data: dict | None = None,
) -> None:
    """`actor` es el email del staff o un actor de sistema (`"stripe"`); no es
    una FK para que la fila sobreviva al borrado del usuario."""
    ActivityLog.objects.create(
        actor_id=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        data=data or {},
    )
