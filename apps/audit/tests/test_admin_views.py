"""`GET /api/admin/activity/`: permiso `activity.view`, ids de Stripe ocultos
sin `payments.transaction_id` y paginación por cursor (`?limit=`, `?before=`)."""
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
    assert [row["id"] for row in body["items"]] == [newer.id, older.id]
    assert body["nextCursor"] is None
    first = body["items"][0]
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

    row = client.get("/api/admin/activity/").json()["items"][0]

    assert row["data"] == {"amountTotal": 7525, "last4": "4242"}


@pytest.mark.django_db
def test_activity_shows_stripe_ids_with_the_transaction_id_permission():
    _payment_activity()
    client = _admin_client("usr_activity_full", ["activity.view", "payments.transaction_id"])

    row = client.get("/api/admin/activity/").json()["items"][0]

    assert row["data"]["sessionId"] == "cs_test_secret"
    assert row["data"]["paymentIntent"] == "pi_test_secret"


@pytest.mark.django_db
def test_activity_shows_stripe_ids_to_a_full_access_role():
    _payment_activity()
    create_staff_user("usr_activity_owner", full_access=True)
    client, _ = session_client("usr_activity_owner")

    row = client.get("/api/admin/activity/").json()["items"][0]

    assert row["data"]["paymentIntent"] == "pi_test_secret"


def _logs(count):
    """Crea `count` filas con `created_at` creciente; devuelve los ids del
    más nuevo al más viejo, que es el orden de la respuesta."""
    base = timezone.now()
    logs = [
        ActivityLog.objects.create(
            action=f"ACTION_{n}", data={}, created_at=base + timezone.timedelta(seconds=n)
        )
        for n in range(count)
    ]
    return [log.id for log in reversed(logs)]


@pytest.mark.django_db
def test_activity_defaults_to_fifty_rows_and_returns_the_next_cursor():
    ids = _logs(51)
    client = _admin_client("usr_activity_page", ["activity.view"])

    body = client.get("/api/admin/activity/").json()

    assert [row["id"] for row in body["items"]] == ids[:50]
    assert body["nextCursor"] == ids[49]


@pytest.mark.django_db
def test_activity_before_cursor_returns_the_following_page():
    ids = _logs(5)
    client = _admin_client("usr_activity_cursor", ["activity.view"])

    first = client.get("/api/admin/activity/?limit=2").json()
    second = client.get(f"/api/admin/activity/?limit=2&before={first['nextCursor']}").json()
    last = client.get(f"/api/admin/activity/?limit=2&before={second['nextCursor']}").json()

    assert [row["id"] for row in first["items"]] == ids[:2]
    assert [row["id"] for row in second["items"]] == ids[2:4]
    assert [row["id"] for row in last["items"]] == ids[4:]
    assert last["nextCursor"] is None


@pytest.mark.django_db
def test_activity_cursor_breaks_created_at_ties_by_id():
    # Varias filas del mismo instante (un lote en la misma transacción) no se
    # pueden repetir ni saltar entre páginas.
    created_at = timezone.now()
    logs = [
        ActivityLog.objects.create(action=f"ACTION_{n}", data={}, created_at=created_at)
        for n in range(3)
    ]
    client = _admin_client("usr_activity_ties", ["activity.view"])

    first = client.get("/api/admin/activity/?limit=2").json()
    second = client.get(f"/api/admin/activity/?limit=2&before={first['nextCursor']}").json()

    seen = [row["id"] for row in first["items"] + second["items"]]
    assert seen == sorted((log.id for log in logs), reverse=True)


@pytest.mark.django_db
def test_activity_caps_the_limit_at_250():
    _logs(251)
    client = _admin_client("usr_activity_cap", ["activity.view"])

    body = client.get("/api/admin/activity/?limit=1000").json()

    assert len(body["items"]) == 250
    assert body["nextCursor"] is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query", ["limit=0", "limit=-1", "limit=abc", "before=abc", "before=999999"]
)
def test_activity_rejects_an_invalid_limit_or_cursor(query):
    client = _admin_client("usr_activity_bad", ["activity.view"])

    response = client.get(f"/api/admin/activity/?{query}")

    assert response.status_code == 400
    assert set(response.json()) == {"error"}
