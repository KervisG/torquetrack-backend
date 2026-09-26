"""`list_activity_page` oculta los ids de Stripe salvo que la view diga que
quien mira puede verlos; no consulta permisos por su cuenta."""
import pytest
from django.utils import timezone

from apps.audit.admin_services import list_activity_page
from apps.audit.models import ActivityLog


def _log(data):
    ActivityLog.objects.create(
        actor_id="stripe", action="PAYMENT_PAID", data=data, created_at=timezone.now()
    )


@pytest.mark.django_db
def test_payment_ids_are_dropped_at_any_depth_by_default():
    _log({"sessionId": "cs_1", "payment": {"paymentIntent": "pi_1", "brand": "visa"}, "n": 1})

    data, _ = list_activity_page()

    assert data["items"][0]["data"] == {"payment": {"brand": "visa"}, "n": 1}


@pytest.mark.django_db
def test_payment_ids_are_kept_when_the_viewer_may_see_them():
    _log({"sessionId": "cs_1", "paymentIntent": "pi_1"})

    data, _ = list_activity_page(can_view_payment_ids=True)
    row = data["items"][0]

    assert row["data"] == {"sessionId": "cs_1", "paymentIntent": "pi_1"}
