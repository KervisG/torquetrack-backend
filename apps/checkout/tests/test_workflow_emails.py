"""Correos de cores y devoluciones: el equipo se entera en `CORES_EMAIL` y
`RETURNS_EMAIL`, y el cliente recibe cada cambio de estado con la respuesta
dirigida a ese mismo buzón."""

import pytest
from django.utils import timezone

from apps.checkout.models import Order
from apps.checkout.services.workflow_emails import notify_core_opened
from tests.factories import create_staff_user, session_client
from tests.fakes import install_resend

BACKGROUND = "apps.checkout.services.workflow_emails.run_in_background"
CORES = "cores@example.com"
RETURNS = "returns@example.com"
BUYER = {"name": "Ana Pérez", "email": "buyer@example.com"}


@pytest.fixture
def sent(monkeypatch, settings):
    settings.RESEND_API_KEY = "re_test_fake"
    settings.FROM_EMAIL = "TorqueTrack <no-reply@example.com>"
    settings.CORES_EMAIL = CORES
    settings.RETURNS_EMAIL = RETURNS
    settings.REPLY_TO_EMAIL = ""
    monkeypatch.setattr(BACKGROUND, lambda func, *args, **kwargs: func(*args, **kwargs))
    return install_resend(monkeypatch).sent


def _order(**data):
    return Order.objects.create(
        id="ord_1",
        number="O20001",
        status="OPEN",
        payment_status="PAID",
        data={"customer": BUYER, **data},
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )


@pytest.fixture
def staff(db):
    create_staff_user(
        "usr_wf", permissions=["orders.view", "orders.status", "cores.manage", "returns.manage"]
    )
    return session_client("usr_wf")[0]


def _patch(staff, workflow):
    return staff.patch("/api/admin/orders/ord_1/", {"workflow": workflow}, format="json")


def _to(sent):
    return [email["to"] for email in sent]


# --- core abierto al pagar --------------------------------------------------


@pytest.mark.django_db
def test_an_opened_core_notifies_the_team_and_the_customer(sent):
    order = _order(coreCase={"status": "AWAITING CORE", "amount": 150.0})

    notify_core_opened(order)

    team, customer = sent
    assert team["to"] == [CORES]
    assert team["subject"] == "Core expected for Order O20001"
    assert "$150.00" in team["html"] and "buyer@example.com" in team["html"]
    assert customer["to"] == ["buyer@example.com"]
    assert customer["subject"] == "Your core return for TorqueTrack Order O20001"
    assert customer["reply_to"] == CORES
    assert "$150.00" in customer["html"]


@pytest.mark.django_db
def test_without_a_cores_mailbox_only_the_customer_is_written(sent, settings):
    settings.CORES_EMAIL = ""
    settings.REPLY_TO_EMAIL = "sales@example.com"

    notify_core_opened(_order(coreCase={"status": "AWAITING CORE", "amount": 150.0}))

    (customer,) = sent
    assert customer["to"] == ["buyer@example.com"]
    assert customer["reply_to"] == "sales@example.com"


@pytest.mark.django_db
def test_an_order_without_a_customer_email_only_notifies_the_team(sent):
    order = _order(coreCase={"status": "AWAITING CORE", "amount": 150.0})
    order.data = {**order.data, "customer": {"name": "Walk-in"}}
    order.save()

    notify_core_opened(order)

    assert _to(sent) == [[CORES]]


@pytest.mark.django_db
def test_customer_text_is_escaped(sent):
    order = _order(coreCase={"status": "AWAITING CORE", "amount": 150.0})
    order.data = {**order.data, "customer": {"name": "<b>Ana</b>", "email": "buyer@example.com"}}
    order.save()

    notify_core_opened(order)

    assert all("<b>Ana</b>" not in email["html"] for email in sent)


# --- cambios de estado desde el panel ---------------------------------------


@pytest.mark.django_db
def test_a_core_status_change_writes_to_the_customer(sent, staff):
    _order(coreCase={"status": "AWAITING CORE", "amount": 150.0})

    response = _patch(staff, {"coreCase": {"status": "RECEIVED", "amount": 150.0}})

    assert response.status_code == 200
    (email,) = sent
    assert email["to"] == ["buyer@example.com"]
    assert email["subject"] == "Core update for TorqueTrack Order O20001"
    assert email["reply_to"] == CORES
    assert "We received your core" in email["html"]


@pytest.mark.django_db
def test_a_refunded_core_states_the_amount(sent, staff):
    _order(coreCase={"status": "ACCEPTED", "amount": 150.0})

    _patch(staff, {"coreCase": {"status": "REFUNDED", "amount": 150.0}})

    assert "$150.00" in sent[0]["html"]


@pytest.mark.django_db
def test_saving_the_same_core_status_sends_nothing(sent, staff):
    _order(coreCase={"status": "RECEIVED", "amount": 150.0})

    _patch(staff, {"coreCase": {"status": "RECEIVED", "amount": 150.0, "notes": "ok"}})

    assert sent == []


@pytest.mark.django_db
def test_a_new_return_notifies_the_team_and_the_customer(sent, staff):
    _order()

    _patch(staff, {"returnCase": {"status": "REQUESTED", "reason": "Wrong part"}})

    team, customer = sent
    assert team["to"] == [RETURNS]
    assert team["subject"] == "Return opened for Order O20001"
    assert "Wrong part" in team["html"]
    assert customer["to"] == ["buyer@example.com"]
    assert customer["subject"] == "Return update for TorqueTrack Order O20001"
    assert customer["reply_to"] == RETURNS


@pytest.mark.django_db
def test_a_later_return_status_only_writes_to_the_customer(sent, staff):
    _order(returnCase={"status": "REQUESTED"})

    _patch(staff, {"returnCase": {"status": "APPROVED"}})

    (email,) = sent
    assert email["to"] == ["buyer@example.com"]
    assert "approved" in email["html"].lower()


@pytest.mark.django_db
def test_a_status_change_of_the_order_alone_sends_no_workflow_email(sent, staff):
    _order(coreCase={"status": "AWAITING CORE", "amount": 150.0})

    staff.patch("/api/admin/orders/ord_1/", {"status": "PROCESSING"}, format="json")

    assert sent == []
