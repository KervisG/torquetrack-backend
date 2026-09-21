"""`admin/dashboard` and `admin/activity` business rules (task 7.1),
near-verbatim ports of `app/api/admin/dashboard/route.ts` and
`app/api/admin/activity/route.ts`.

Raw SQL is used for the dashboard aggregate (same precedent as
`apps.checkout.services.next_order_number`/`apps.quotes.services.
next_quote_number`): summing a JSONField key across rows is a single
well-defined query that the legacy route already expresses as SQL, and
Django's JSON aggregation ORM API would be less direct than reusing it.
"""
from __future__ import annotations

from django.db import connection

from apps.backoffice.models import ActivityLog


def get_dashboard_counts() -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select
                (select count(*) from orders) as orders,
                (select count(*) from quotes where status = 'ACTIVE') as active_quotes,
                (select count(*) from quotes where status = 'BUILDING') as building_quotes,
                (select count(*) from carts where updated_at > now() - interval '30 minutes')
                    as active_carts,
                (select count(*) from carts where updated_at <= now() - interval '30 minutes')
                    as abandoned_carts,
                (select coalesce(sum((data->'totals'->>'total')::numeric), 0) from orders
                    where created_at::date = current_date and payment_status = 'PAID')
                    as sales_today
            """
        )
        columns = [column[0] for column in cursor.description]
        row = cursor.fetchone()

    values = dict(zip(columns, row))
    return {
        "counts": {
            "orders": values["orders"],
            "activeQuotes": values["active_quotes"],
            "buildingQuotes": values["building_quotes"],
            "activeCarts": values["active_carts"],
            "abandonedCarts": values["abandoned_carts"],
            "salesToday": float(values["sales_today"]),
        }
    }


def list_recent_activity(limit: int = 250) -> list[dict]:
    """Mirror `select * from activity_logs order by created_at desc limit
    250`'s raw-row shape (snake_case column names, as node-pg returns
    them) rather than the model's usual camelCase serialization."""
    logs = ActivityLog.objects.order_by("-created_at")[:limit]
    return [
        {
            "id": log.id,
            "actor_id": log.actor_id,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "data": log.data,
            "created_at": log.created_at,
        }
        for log in logs
    ]
