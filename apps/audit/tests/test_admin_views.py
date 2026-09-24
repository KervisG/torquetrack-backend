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


def _payment_activity():
    return ActivityLog.objects.create(
        actor_id="stripe",
        action="PAYMENT_PAID",
        entity_type="ORDER",
        entity_id="O1",
        data={
            "sessionId": "cs_test_secret",
            "paymentIntent": "pi_test_secret",
            "amountTotal": 7525,
            "last4": "4242",
        },
        created_at=timezone.now(),
    )


@pytest.mark.django_db
def test_activity_hides_stripe_ids_without_the_transaction_id_permission():
    _payment_activity()
    client = _admin_client("usr_activity_redacted", ["activity.view"])

    row = client.get("/api/admin/activity/").json()[0]

    assert row["data"] == {"amountTotal": 7525, "last4": "4242"}


@pytest.mark.django_db
def test_activity_shows_stripe_ids_with_the_transaction_id_permission():
    _payment_activity()
    client = _admin_client("usr_activity_full", ["activity.view", "payments.transaction_id"])

    row = client.get("/api/admin/activity/").json()[0]

    assert row["data"]["sessionId"] == "cs_test_secret"
    assert row["data"]["paymentIntent"] == "pi_test_secret"


@pytest.mark.django_db
def test_activity_shows_stripe_ids_to_a_full_access_role():
    _payment_activity()
    create_staff_user("usr_activity_owner", full_access=True)
    client, _ = session_client("usr_activity_owner")

    row = client.get("/api/admin/activity/").json()[0]

    assert row["data"]["paymentIntent"] == "pi_test_secret"
