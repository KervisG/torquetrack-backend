"""Stage A binding test for `activity_logs` (design decision #3).

Only proves the read/write binding this phase's Stripe webhook write needs;
the `admin/activity` read endpoint is Phase 7 scope, not tested here.
"""
import pytest
from django.utils import timezone

from apps.backoffice.models import ActivityLog


@pytest.mark.django_db
def test_creates_and_reads_activity_log_row():
    ActivityLog.objects.create(
        actor_id="stripe",
        action="PAYMENT_PAID",
        entity_type="ORDER",
        entity_id="ord_1",
        data={"sessionId": "cs_test_1"},
        created_at=timezone.now(),
    )

    row = ActivityLog.objects.get(entity_id="ord_1")

    assert row.action == "PAYMENT_PAID"
    assert row.actor_id == "stripe"
    assert row.data["sessionId"] == "cs_test_1"
