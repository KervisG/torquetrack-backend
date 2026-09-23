from __future__ import annotations

from apps.audit.models import ActivityLog


def list_recent_activity(limit: int = 250) -> list[dict]:
    logs = ActivityLog.objects.order_by("-created_at")[:limit]
    return [
        {
            "id": log.id,
            "actorId": log.actor_id,
            "action": log.action,
            "entityType": log.entity_type,
            "entityId": log.entity_id,
            "data": log.data,
            "createdAt": log.created_at,
        }
        for log in logs
    ]
