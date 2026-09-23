import pytest

from apps.audit.models import ActivityLog
from apps.audit.services import record_activity


@pytest.mark.django_db
def test_record_activity_writes_the_expected_row():
    record_activity(
        "stripe",
        "PAYMENT_PAID",
        entity_type="ORDER",
        entity_id="ord_1",
        data={"sessionId": "cs_test_1"},
    )

    row = ActivityLog.objects.get()
    assert row.actor_id == "stripe"
    assert row.action == "PAYMENT_PAID"
    assert row.entity_type == "ORDER"
    assert row.entity_id == "ord_1"
    assert row.data == {"sessionId": "cs_test_1"}
    assert row.created_at is not None


@pytest.mark.django_db
def test_record_activity_defaults_optional_fields():
    record_activity(None, "SYSTEM_EVENT")

    row = ActivityLog.objects.get()
    assert row.actor_id is None
    assert row.entity_type is None
    assert row.entity_id is None
    assert row.data == {}
