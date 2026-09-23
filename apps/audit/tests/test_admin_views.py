"""Tests de `GET /api/admin/activity` (exige `activity.view`).

El body usa claves camelCase (`actorId`, `entityType`, `entityId`,
`createdAt`) como el resto de la API. Las filas se arman con
`record_activity` y con el ORM cuando el test necesita fijar la fecha.
"""
import pytest
from django.utils import timezone

from apps.audit.models import ActivityLog
from tests.factories import create_staff_user, session_client


def _admin_client(user_id, permissions):
    create_staff_user(user_id, permissions=permissions)
    client, _ = session_client(user_id)
    return client


@pytest.mark.django_db
def test_activity_returns_403_without_permission():
    client = _admin_client("usr_activity_no_perm", [])

    response = client.get("/api/admin/activity/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_activity_returns_recent_logs_newest_first_in_camel_case():
    older = ActivityLog.objects.create(
        actor_id="ada@example.com",
        action="USER_CREATED",
        entity_type="USER",
        entity_id="U1",
        data={},
        created_at=timezone.now() - timezone.timedelta(hours=1),
    )
    newer = ActivityLog.objects.create(
        actor_id="ada@example.com",
        action="QUOTE_DELETED",
        entity_type="QUOTE",
        entity_id="Q1",
        data={"number": "Q10003"},
        created_at=timezone.now(),
    )
    client = _admin_client("usr_activity", ["activity.view"])

    response = client.get("/api/admin/activity/")

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body] == [newer.id, older.id]
    first = body[0]
    assert set(first) == {
        "id",
        "actorId",
        "action",
        "entityType",
        "entityId",
        "data",
        "createdAt",
    }
    assert first["actorId"] == "ada@example.com"
    assert first["action"] == "QUOTE_DELETED"
    assert first["entityType"] == "QUOTE"
    assert first["entityId"] == "Q1"
    assert first["data"] == {"number": "Q10003"}
