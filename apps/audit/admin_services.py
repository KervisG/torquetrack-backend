from __future__ import annotations

from apps.audit.models import ActivityLog

# Ids de Stripe que escriben los pagos en `data`. Verlos exige lo mismo que en
# el detalle del pedido (`payments.transaction_id`), no solo `activity.view`.
PAYMENT_ID_KEYS = frozenset({"sessionId", "paymentIntent"})


def _without_keys(value, keys: frozenset[str]):
    if isinstance(value, dict):
        return {k: _without_keys(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_without_keys(item, keys) for item in value]
    return value


def list_recent_activity(limit: int = 250, *, can_view_payment_ids: bool = False) -> list[dict]:
    """`can_view_payment_ids` lo resuelve la view con el permiso de quien
    mira, así `audit` no depende del catálogo de permisos de los dominios."""
    logs = ActivityLog.objects.order_by("-created_at")[:limit]
    return [
        {
            "id": log.id,
            "actorId": log.actor_id,
            "action": log.action,
            "entityType": log.entity_type,
            "entityId": log.entity_id,
            "data": log.data if can_view_payment_ids else _without_keys(log.data, PAYMENT_ID_KEYS),
            "createdAt": log.created_at,
        }
        for log in logs
    ]
