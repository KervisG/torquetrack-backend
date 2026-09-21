"""`GET /api/admin/dashboard` and `GET /api/admin/activity` (task 7.1),
pinned against `app/api/admin/dashboard/route.ts` and
`app/api/admin/activity/route.ts`.
"""
import json
from importlib import import_module

import pytest
from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.backoffice.models import ActivityLog


def _insert_user(user_id, role="authorized", permissions=None, active=True):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into users (id, username, password_hash, role, active, "
            "permissions) values (%s, %s, %s, %s, %s, %s::jsonb)",
            [
                user_id,
                f"{user_id}@example.com",
                "scrypt$salt$hash",
                role,
                active,
                json.dumps(permissions or []),
            ],
        )


def _admin_client(user_id):
    engine = import_module(settings.SESSION_ENGINE)
    store = engine.SessionStore()
    store["user_id"] = user_id
    store.save()
    client = APIClient()
    client.cookies["tt_admin"] = store.session_key
    return client


def _insert_order(order_id, number, data, payment_status="UNPAID", created_at=None):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into orders (id, number, status, payment_status, data, created_at)"
            " values (%s, %s, 'OPEN', %s, %s::jsonb, %s)",
            [order_id, number, payment_status, json.dumps(data), created_at or timezone.now()],
        )


def _insert_cart(cart_id, updated_at):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into carts (id, data, updated_at) values (%s, '{}', %s)",
            [cart_id, updated_at],
        )


def _insert_quote(quote_id, number, status):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into quotes (id, number, status, data, created_at, updated_at)"
            " values (%s, %s, %s, '{}', now(), now())",
            [quote_id, number, status],
        )


# --- dashboard --------------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_returns_403_without_permission():
    _insert_user("usr_dash_no_perm", permissions=[])
    client = _admin_client("usr_dash_no_perm")

    response = client.get("/api/admin/dashboard/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_dashboard_returns_aggregate_counts():
    _insert_user("usr_dash", permissions=["dashboard.view"])
    _insert_order("OID_1", "O10001", {"totals": {"total": 100.0}}, payment_status="PAID")
    _insert_order("OID_2", "O10002", {"totals": {"total": 50.0}}, payment_status="UNPAID")
    _insert_cart("cart_active", timezone.now())
    _insert_cart("cart_abandoned", timezone.now() - timezone.timedelta(minutes=45))
    _insert_quote("quo_active", "Q10001", "ACTIVE")
    _insert_quote("quo_building", "Q10002", "BUILDING")

    client = _admin_client("usr_dash")
    response = client.get("/api/admin/dashboard/")

    assert response.status_code == 200
    counts = response.json()["counts"]
    assert counts["orders"] == 2
    assert counts["activeQuotes"] == 1
    assert counts["buildingQuotes"] == 1
    assert counts["activeCarts"] == 1
    assert counts["abandonedCarts"] == 1
    assert counts["salesToday"] == 100.0


# --- activity -----------------------------------------------------------


@pytest.mark.django_db
def test_activity_returns_403_without_permission():
    _insert_user("usr_activity_no_perm", permissions=[])
    client = _admin_client("usr_activity_no_perm")

    response = client.get("/api/admin/activity/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_activity_returns_recent_logs_newest_first():
    _insert_user("usr_activity", permissions=["activity.view"])
    older = ActivityLog.objects.create(
        actor_id="usr_activity",
        action="USER_CREATED",
        entity_type="USER",
        entity_id="U1",
        data={},
        created_at=timezone.now() - timezone.timedelta(hours=1),
    )
    newer = ActivityLog.objects.create(
        actor_id="usr_activity",
        action="QUOTE_DELETED",
        entity_type="QUOTE",
        entity_id="Q1",
        data={"number": "Q10003"},
        created_at=timezone.now(),
    )

    client = _admin_client("usr_activity")
    response = client.get("/api/admin/activity/")

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body[:2]] == [newer.id, older.id]
    assert body[0]["action"] == "QUOTE_DELETED"
    assert body[0]["entity_id"] == "Q1"
