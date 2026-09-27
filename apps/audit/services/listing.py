from __future__ import annotations

from django.db.models import Q

from apps.audit.models import ActivityLog

# Ids de Stripe que escriben los pagos en `data`. Verlos exige lo mismo que en
# el detalle del pedido (`payments.transaction_id`), no solo `activity.view`.
PAYMENT_ID_KEYS = frozenset({"sessionId", "paymentIntent", "stripeRefundId"})


def _without_keys(value, keys: frozenset[str]):
    if isinstance(value, dict):
        return {k: _without_keys(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_without_keys(item, keys) for item in value]
    return value


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 250


def _parse_positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _serialize(log: ActivityLog, can_view_payment_ids: bool) -> dict:
    return {
        "id": log.id,
        "actorId": log.actor_id,
        "action": log.action,
        "entityType": log.entity_type,
        "entityId": log.entity_id,
        "data": log.data if can_view_payment_ids else _without_keys(log.data, PAYMENT_ID_KEYS),
        "createdAt": log.created_at,
    }


def list_activity_page(
    limit=None, before=None, *, can_view_payment_ids: bool = False
) -> tuple[dict, int]:
    """Página de la bitácora, de la más nueva a la más vieja.

    `before` es el id de la última fila de la página anterior (`nextCursor`).
    El cursor es por `(created_at, id)` y no solo por id: `created_at` es lo
    que ordena la bitácora y varias filas pueden compartir el mismo instante.
    `can_view_payment_ids` lo resuelve la view con el permiso de quien mira,
    así `audit` no depende del catálogo de permisos de los dominios.
    """
    size = DEFAULT_PAGE_SIZE
    if limit is not None:
        size = _parse_positive_int(limit)
        if size is None:
            return {"error": "Invalid limit"}, 400
        size = min(size, MAX_PAGE_SIZE)

    logs = ActivityLog.objects.order_by("-created_at", "-id")
    if before is not None:
        cursor_id = _parse_positive_int(before)
        cursor = ActivityLog.objects.filter(id=cursor_id).first() if cursor_id else None
        if cursor is None:
            return {"error": "Invalid cursor"}, 400
        logs = logs.filter(
            Q(created_at__lt=cursor.created_at) | Q(created_at=cursor.created_at, id__lt=cursor.id)
        )

    # Una fila de más dice si hay otra página sin un COUNT aparte.
    rows = list(logs[: size + 1])
    page = rows[:size]
    return {
        "items": [_serialize(log, can_view_payment_ids) for log in page],
        "nextCursor": page[-1].id if len(rows) > size else None,
    }, 200
