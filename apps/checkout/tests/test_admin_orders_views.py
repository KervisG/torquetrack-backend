"""Tests de `admin/orders`, `admin/orders/[id]`,
`admin/orders/[id]/payment-link` y `admin/orders/[id]/take-payment`.

`PATCH`/`DELETE admin/orders/[id]` hacen dos chequeos SEPARADOS: sesión de
staff (401 sin sesión) y permiso (403 sin permiso), donde el permiso exigido
depende del cambio pedido. El listado, payment-link y take-payment usan en
cambio `HasTorqueTrackPermission` con un único `required_permission`.

Las APIs reales de Stripe y de Resend nunca se llaman: se parchean sus
adaptadores, `apps.integrations.payments.stripe.create_checkout_session` y
`apps.integrations.email.resend.send_email` (`tests/fakes.py`).
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.checkout.models import Order, Payment
from apps.integrations.exceptions import ProviderError
from tests.factories import activity_count, create_staff_user, session_client
from tests.fakes import install_resend

CREATE_SESSION = "apps.integrations.payments.stripe.create_checkout_session"


def _insert_user(user_id, permissions=None, active=True, full_access=False):
    create_staff_user(
        user_id, permissions=permissions, active=active, full_access=full_access
    )


def _admin_client(user_id):
    client, _ = session_client(user_id)
    return client


def _make_order(order_id="ord_1", number="O20001", data=None, payment_status="UNPAID", **kwargs):
    fields = {
        "id": order_id,
        "number": number,
        "status": "OPEN",
        "payment_status": payment_status,
        "data": data or {},
        "created_at": timezone.now(),
        "updated_at": timezone.now(),
        **kwargs,
    }
    return Order.objects.create(**fields)


def _fake_session(session_id="cs_test_admin", url="https://checkout.stripe.com/pay/cs_test_admin"):
    return {"id": session_id, "url": url}


# --- list (GET) --------------------------------------------------------


@pytest.mark.django_db
def test_list_returns_403_without_orders_view_permission():
    _insert_user("usr_list_no_perm", permissions=[])
    client = _admin_client("usr_list_no_perm")

    response = client.get("/api/admin/orders/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_list_returns_orders_with_expected_shape():
    _insert_user("usr_list", permissions=["orders.view"])
    _make_order(data={"customer": {"email": "no-fk@example.com"}})
    client = _admin_client("usr_list")

    response = client.get("/api/admin/orders/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["number"] == "O20001"
    assert body[0]["paymentStatus"] == "UNPAID"
    assert body[0]["customer"]["email"] == "no-fk@example.com"


@pytest.mark.django_db
def test_list_includes_payments_without_the_provider_transaction_id():
    """El detalle del pedido en el panel muestra sus pagos. El id de Stripe
    queda fuera: verlo es `payments.transaction_id`, no `orders.view`."""
    _insert_user("usr_list_payments", permissions=["orders.view"])
    order = _make_order()
    Payment.objects.create(
        id="PAY_1",
        order=order,
        provider="stripe",
        provider_id="cs_secret_session",
        status="PENDING",
        amount=125.5,
        data={"source": "EMPLOYEE_TAKE_PAYMENT"},
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )
    client = _admin_client("usr_list_payments")

    response = client.get("/api/admin/orders/")

    assert response.status_code == 200
    payments = response.json()[0]["payments"]
    assert len(payments) == 1
    assert payments[0]["id"] == "PAY_1"
    assert payments[0]["provider"] == "stripe"
    assert payments[0]["status"] == "PENDING"
    assert payments[0]["amount"] == 125.5
    assert payments[0]["source"] == "EMPLOYEE_TAKE_PAYMENT"
    assert payments[0]["createdAt"]
    assert "cs_secret_session" not in response.content.decode()


# --- PATCH status -----------------------------------------------------


@pytest.mark.django_db
def test_patch_status_returns_401_without_session():
    _make_order()

    response = APIClient().patch(
        "/api/admin/orders/ord_1/", {"status": "PROCESSING"}, format="json"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_patch_cancel_status_requires_orders_cancel_permission():
    _insert_user("usr_patch1", permissions=["orders.status"])
    _make_order()
    client = _admin_client("usr_patch1")

    response = client.patch(
        "/api/admin/orders/ord_1/", {"status": "CANCELLED"}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_patch_non_cancel_status_requires_orders_status_permission():
    _insert_user("usr_patch2", permissions=["orders.cancel"])
    _make_order()
    client = _admin_client("usr_patch2")

    response = client.patch(
        "/api/admin/orders/ord_1/", {"status": "PROCESSING"}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_patch_status_rejects_invalid_value():
    _insert_user("usr_patch3", permissions=["orders.status"])
    _make_order()
    client = _admin_client("usr_patch3")

    response = client.patch(
        "/api/admin/orders/ord_1/", {"status": "NOT_A_STATUS"}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_patch_status_updates_and_logs_activity():
    _insert_user("usr_patch4", permissions=["orders.status"])
    _make_order()
    client = _admin_client("usr_patch4")

    response = client.patch(
        "/api/admin/orders/ord_1/", {"status": "processing"}, format="json"
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": "PROCESSING"}
    order = Order.objects.get(pk="ord_1")
    assert order.status == "PROCESSING"
    assert activity_count(action="ORDER_STATUS_CHANGED", entity_id="ord_1") >= 1


@pytest.mark.django_db
def test_patch_status_returns_404_for_unknown_order():
    _insert_user("usr_patch5", permissions=["orders.status"])
    client = _admin_client("usr_patch5")

    response = client.patch(
        "/api/admin/orders/does-not-exist/", {"status": "PROCESSING"}, format="json"
    )

    assert response.status_code == 404


# --- PATCH workflow -----------------------------------------------------


@pytest.mark.django_db
def test_patch_workflow_core_case_requires_cores_manage_permission():
    _insert_user("usr_workflow1", permissions=[])
    _make_order()
    client = _admin_client("usr_workflow1")

    response = client.patch(
        "/api/admin/orders/ord_1/",
        {"workflow": {"coreCase": {"status": "received"}}},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_patch_workflow_return_case_requires_returns_manage_permission():
    _insert_user("usr_workflow2", permissions=[])
    _make_order()
    client = _admin_client("usr_workflow2")

    response = client.patch(
        "/api/admin/orders/ord_1/",
        {"workflow": {"returnCase": {"status": "requested"}}},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_patch_workflow_merges_core_case_into_data():
    _insert_user("usr_workflow3", permissions=["cores.manage"])
    _make_order()
    client = _admin_client("usr_workflow3")

    response = client.patch(
        "/api/admin/orders/ord_1/",
        {"workflow": {"coreCase": {"status": "received", "note": "ok"}}},
        format="json",
    )

    assert response.status_code == 200
    order = Order.objects.get(pk="ord_1")
    assert order.data["coreCase"]["status"] == "RECEIVED"
    assert order.data["coreCase"]["updatedBy"] == "usr_workflow3@example.com"
    assert activity_count(action="ORDER_WORKFLOW_UPDATED", entity_id="ord_1") >= 1


@pytest.mark.django_db
def test_patch_neither_status_nor_workflow_returns_400():
    _insert_user("usr_workflow4", permissions=[])
    _make_order()
    client = _admin_client("usr_workflow4")

    response = client.patch("/api/admin/orders/ord_1/", {}, format="json")

    assert response.status_code == 400


# --- DELETE ---------------------------------------------------------------


@pytest.mark.django_db
def test_delete_returns_401_without_session():
    _make_order()

    response = APIClient().delete("/api/admin/orders/ord_1/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_delete_returns_403_without_orders_cancel_permission():
    _insert_user("usr_delete1", permissions=[])
    _make_order()
    client = _admin_client("usr_delete1")

    response = client.delete("/api/admin/orders/ord_1/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_delete_returns_409_when_order_is_not_unpaid():
    _insert_user("usr_delete2", permissions=["orders.cancel"])
    _make_order(payment_status="PAID")
    client = _admin_client("usr_delete2")

    response = client.delete("/api/admin/orders/ord_1/")

    assert response.status_code == 409
    assert Order.objects.filter(pk="ord_1").exists()


@pytest.mark.django_db
def test_delete_removes_unpaid_order_and_its_payments():
    _insert_user("usr_delete3", permissions=["orders.cancel"])
    order = _make_order()
    Payment.objects.create(
        id="pay_1",
        order=order,
        provider="stripe",
        provider_id="cs_x",
        status="PENDING",
        amount=10,
        data={},
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )
    client = _admin_client("usr_delete3")

    response = client.delete("/api/admin/orders/ord_1/")

    assert response.status_code == 200
    assert not Order.objects.filter(pk="ord_1").exists()
    assert not Payment.objects.filter(id="pay_1").exists()
    assert activity_count(action="UNPAID_ORDER_DELETED", entity_id="ord_1") >= 1


# --- payment-link (POST) --------------------------------------------------


@pytest.mark.django_db
def test_payment_link_returns_403_without_payments_take_permission():
    _insert_user("usr_link1", permissions=[])
    _make_order()
    client = _admin_client("usr_link1")

    response = client.post("/api/admin/orders/ord_1/payment-link/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_payment_link_returns_409_when_already_paid():
    _insert_user("usr_link2", permissions=["payments.take"])
    _make_order(payment_status="PAID")
    client = _admin_client("usr_link2")

    response = client.post("/api/admin/orders/ord_1/payment-link/")

    assert response.status_code == 409


@pytest.mark.django_db
def test_payment_link_creates_payment_updates_status_and_emails_customer(monkeypatch, settings):
    settings.RESEND_API_KEY = "re_test_fake"
    settings.FROM_EMAIL = "sales@torquetrackdiesel.com"
    _insert_user("usr_link3", permissions=["payments.take"])
    _make_order(data={"customer": {"email": "buyer@example.com"}, "totals": {"total": 150.5}})
    client = _admin_client("usr_link3")

    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    resend = install_resend(monkeypatch)

    response = client.post("/api/admin/orders/ord_1/payment-link/")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["emailed"] is True
    assert resend.sent[0]["to"] == ["buyer@example.com"]

    order = Order.objects.get(pk="ord_1")
    assert order.status == "PENDING_PAYMENT"
    payment = Payment.objects.get(order=order)
    assert payment.data["adminGenerated"] is True


@pytest.mark.django_db
def test_payment_link_without_customer_email_is_not_emailed(monkeypatch):
    _insert_user("usr_link4", permissions=["payments.take"])
    _make_order(data={"totals": {"total": 50.0}})
    client = _admin_client("usr_link4")

    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = client.post("/api/admin/orders/ord_1/payment-link/")

    assert response.status_code == 200
    assert response.json()["emailed"] is False


@pytest.mark.django_db
def test_payment_link_returns_502_on_stripe_failure(monkeypatch):
    _insert_user("usr_link5", permissions=["payments.take"])
    _make_order()
    client = _admin_client("usr_link5")

    def _boom(**kwargs):
        raise ProviderError("Could not create payment link")

    monkeypatch.setattr(CREATE_SESSION, _boom)

    response = client.post("/api/admin/orders/ord_1/payment-link/")

    assert response.status_code == 502


# --- take-payment (POST) --------------------------------------------------


@pytest.mark.django_db
def test_take_payment_returns_403_without_payments_take_permission():
    _insert_user("usr_take1", permissions=[])
    _make_order()
    client = _admin_client("usr_take1")

    response = client.post("/api/admin/orders/ord_1/take-payment/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_take_payment_returns_409_when_already_paid():
    _insert_user("usr_take2", permissions=["payments.take"])
    _make_order(payment_status="PAID")
    client = _admin_client("usr_take2")

    response = client.post("/api/admin/orders/ord_1/take-payment/")

    assert response.status_code == 409


@pytest.mark.django_db
def test_take_payment_creates_payment_and_logs_activity_without_status_change(monkeypatch):
    _insert_user("usr_take3", permissions=["payments.take"])
    _make_order(data={"totals": {"total": 75.25}})
    client = _admin_client("usr_take3")

    monkeypatch.setattr(CREATE_SESSION, lambda **kwargs: _fake_session())

    response = client.post("/api/admin/orders/ord_1/take-payment/")

    assert response.status_code == 200
    order = Order.objects.get(pk="ord_1")
    assert order.status == "OPEN"  # unchanged, unlike payment-link
    payment = Payment.objects.get(order=order)
    assert payment.data["source"] == "EMPLOYEE_TAKE_PAYMENT"
    assert payment.data["employee"] == "usr_take3@example.com"
    assert activity_count(action="TAKE_PAYMENT_STARTED", entity_id="ord_1") >= 1


@pytest.mark.django_db
def test_take_payment_returns_502_on_stripe_failure(monkeypatch):
    _insert_user("usr_take4", permissions=["payments.take"])
    _make_order()
    client = _admin_client("usr_take4")

    def _boom(**kwargs):
        raise ProviderError("Could not start secure payment")

    monkeypatch.setattr(CREATE_SESSION, _boom)

    response = client.post("/api/admin/orders/ord_1/take-payment/")

    assert response.status_code == 502
