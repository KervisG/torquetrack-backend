
import logging
from datetime import UTC, datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.checkout.models import Order, Payment
from apps.common.emails import email_logo_url
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
def test_list_date_today_keeps_only_orders_placed_on_the_florida_day(monkeypatch):
    # 23:30 EDT del 5 de octubre = 03:30 UTC del 6: en Florida sigue siendo el 5.
    _insert_user("usr_list_today", permissions=["orders.view"])
    client = _admin_client("usr_list_today")
    now = datetime(2026, 10, 6, 3, 30, tzinfo=UTC)
    monkeypatch.setattr(timezone, "now", lambda: now)
    _make_order("ord_late", "O20001", created_at=now)
    _make_order("ord_morning", "O20002", created_at=datetime(2026, 10, 5, 5, tzinfo=UTC))
    # 23:00 EDT del 4 de octubre: ayer en Florida aunque en UTC ya sea el 5.
    _make_order("ord_yesterday", "O20003", created_at=datetime(2026, 10, 5, 3, tzinfo=UTC))

    today = client.get("/api/admin/orders/?date=today")
    every = client.get("/api/admin/orders/")

    assert today.status_code == 200
    assert [row["number"] for row in today.json()] == ["O20002", "O20001"]
    assert len(every.json()) == 3


@pytest.mark.django_db
def test_list_rejects_an_unknown_date_filter():
    _insert_user("usr_list_bad_date", permissions=["orders.view"])
    client = _admin_client("usr_list_bad_date")

    response = client.get("/api/admin/orders/?date=yesterday")

    assert response.status_code == 400
    assert response.json() == {"error": "date must be today", "field": "date"}


@pytest.mark.django_db
def test_list_includes_the_fulfillment_fields():
    """El envío va en columnas propias de `Order`, separado de `status`; el
    enlace de seguimiento lo arma el backend según el transportista."""
    _insert_user("usr_list_fulfillment", permissions=["orders.view"])
    shipped_at = timezone.now()
    _make_order(
        payment_status="PAID",
        fulfillment_status="SHIPPED",
        carrier="USPS",
        tracking_number="9400111899223100000000",
        shipped_at=shipped_at,
    )
    _make_order(order_id="ord_2", number="O20002")
    client = _admin_client("usr_list_fulfillment")

    body = client.get("/api/admin/orders/").json()

    shipped, pending = body
    assert shipped["fulfillmentStatus"] == "SHIPPED"
    assert shipped["carrier"] == "USPS"
    assert shipped["trackingNumber"] == "9400111899223100000000"
    assert shipped["trackingUrl"] == (
        "https://tools.usps.com/go/TrackConfirmAction?tLabels=9400111899223100000000"
    )
    assert shipped["shippedAt"]
    assert shipped["deliveredAt"] is None
    assert pending["fulfillmentStatus"] == "UNFULFILLED"
    assert pending["carrier"] == ""
    assert pending["trackingNumber"] == ""
    assert pending["trackingUrl"] is None
    assert pending["shippedAt"] is None


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


def _paid_order_with_stripe_ids():
    order = _make_order(
        payment_status="PAID",
        data={"payment": {"provider": "stripe", "last4": "4242", "paymentIntent": "pi_secret"}},
    )
    Payment.objects.create(
        id="PAY_PAID",
        order=order,
        provider="stripe",
        provider_id="cs_secret_session",
        status="PAID",
        amount=10,
        data={"payment_intent": "pi_secret", "sessionId": "cs_secret_session"},
    )


@pytest.mark.django_db
def test_list_hides_the_payment_intent_in_order_data_without_transaction_id():
    _insert_user("usr_list_pi", permissions=["orders.view"])
    _paid_order_with_stripe_ids()

    response = _admin_client("usr_list_pi").get("/api/admin/orders/")

    body = response.content.decode()
    assert "pi_secret" not in body
    assert "cs_secret_session" not in body
    assert response.json()[0]["payment"] == {"provider": "stripe", "last4": "4242"}


@pytest.mark.django_db
def test_list_includes_stripe_ids_with_payments_transaction_id():
    _insert_user("usr_list_tx", permissions=["orders.view", "payments.transaction_id"])
    _paid_order_with_stripe_ids()

    row = _admin_client("usr_list_tx").get("/api/admin/orders/").json()[0]

    assert row["payment"]["paymentIntent"] == "pi_secret"
    assert row["payments"][0]["providerId"] == "cs_secret_session"
    assert row["payments"][0]["paymentIntent"] == "pi_secret"


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
def test_patch_status_rejects_a_jump():
    """`OPEN` no salta a `COMPLETED`: hay que pasar por `PROCESSING`."""
    _insert_user("usr_patch_jump", permissions=["orders.status"])
    _make_order()
    client = _admin_client("usr_patch_jump")

    response = client.patch("/api/admin/orders/ord_1/", {"status": "COMPLETED"}, format="json")

    assert response.status_code == 409
    assert response.json() == {"error": "Cannot move order from OPEN to COMPLETED"}
    assert Order.objects.get(pk="ord_1").status == "OPEN"
    assert activity_count(action="ORDER_STATUS_CHANGED", entity_id="ord_1") == 0


@pytest.mark.django_db
def test_patch_status_rejects_a_move_out_of_a_terminal_status():
    _insert_user("usr_patch_done", permissions=["orders.status", "orders.cancel"])
    _make_order(status="COMPLETED")
    client = _admin_client("usr_patch_done")

    response = client.patch("/api/admin/orders/ord_1/", {"status": "CANCELLED"}, format="json")

    assert response.status_code == 409
    assert response.json() == {"error": "Cannot move order from COMPLETED to CANCELLED"}
    assert Order.objects.get(pk="ord_1").status == "COMPLETED"


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
def test_patch_applies_status_and_workflow_together():
    _insert_user("usr_both", permissions=["orders.status", "cores.manage"])
    _make_order()

    response = _admin_client("usr_both").patch(
        "/api/admin/orders/ord_1/",
        {"status": "processing", "workflow": {"coreCase": {"status": "received"}}},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PROCESSING"
    assert body["coreCase"]["status"] == "RECEIVED"
    order = Order.objects.get(pk="ord_1")
    assert order.status == "PROCESSING"
    assert order.data["coreCase"]["status"] == "RECEIVED"
    assert activity_count(action="ORDER_STATUS_CHANGED", entity_id="ord_1") == 1
    assert activity_count(action="ORDER_WORKFLOW_UPDATED", entity_id="ord_1") == 1


@pytest.mark.django_db
def test_patch_with_an_invalid_workflow_does_not_change_the_status():
    _insert_user("usr_both2", permissions=["orders.status", "cores.manage"])
    _make_order()

    response = _admin_client("usr_both2").patch(
        "/api/admin/orders/ord_1/",
        {"status": "processing", "workflow": {"coreCase": {"status": "bogus"}}},
        format="json",
    )

    assert response.status_code == 400
    order = Order.objects.get(pk="ord_1")
    assert order.status == "OPEN"
    assert "coreCase" not in order.data
    assert activity_count(action="ORDER_STATUS_CHANGED", entity_id="ord_1") == 0


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
def test_payment_link_hides_the_stripe_error_behind_a_502(monkeypatch, caplog):
    _insert_user("usr_link5", permissions=["payments.take"])
    _make_order()
    client = _admin_client("usr_link5")

    def _boom(**kwargs):
        raise ProviderError("Invalid API Key for account acct_internal_123")

    monkeypatch.setattr(CREATE_SESSION, _boom)

    with caplog.at_level(logging.WARNING, logger="apps.checkout.services.admin"):
        response = client.post("/api/admin/orders/ord_1/payment-link/")

    assert response.status_code == 502
    assert response.json() == {"error": "Stripe request failed; see server logs."}
    assert "acct_internal_123" in caplog.text


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
    assert order.status == "OPEN"  # a diferencia del link de pago
    payment = Payment.objects.get(order=order)
    assert payment.data["source"] == "EMPLOYEE_TAKE_PAYMENT"
    assert payment.data["employee"] == "usr_take3@example.com"
    assert activity_count(action="TAKE_PAYMENT_STARTED", entity_id="ord_1") >= 1


@pytest.mark.django_db
def test_take_payment_hides_the_stripe_error_behind_a_502(monkeypatch, caplog):
    _insert_user("usr_take4", permissions=["payments.take"])
    _make_order()
    client = _admin_client("usr_take4")

    def _boom(**kwargs):
        raise ProviderError("Invalid API Key for account acct_internal_123")

    monkeypatch.setattr(CREATE_SESSION, _boom)

    with caplog.at_level(logging.WARNING, logger="apps.checkout.services.admin"):
        response = client.post("/api/admin/orders/ord_1/take-payment/")

    assert response.status_code == 502
    assert response.json() == {"error": "Stripe request failed; see server logs."}
    assert "acct_internal_123" in caplog.text


# --- Estados cerrados y bloqueo de fila -------------------------------------


def _forbid_stripe(monkeypatch):
    def _boom(**kwargs):
        raise AssertionError("Stripe must not be called for a closed order")

    monkeypatch.setattr(CREATE_SESSION, _boom)


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["CANCELLED", "REJECTED"])
def test_payment_link_returns_409_for_a_closed_order(monkeypatch, status):
    _insert_user("usr_link_closed", permissions=["payments.take"])
    _make_order(status=status, data={"totals": {"total": 50.0}})
    _forbid_stripe(monkeypatch)

    response = _admin_client("usr_link_closed").post("/api/admin/orders/ord_1/payment-link/")

    assert response.status_code == 409
    assert response.json() == {"error": "Closed orders cannot be paid"}
    assert Order.objects.get(pk="ord_1").status == status
    assert not Payment.objects.filter(order_id="ord_1").exists()



@pytest.mark.django_db
@pytest.mark.parametrize("status", ["CANCELLED", "REJECTED"])
def test_take_payment_returns_409_for_a_closed_order(monkeypatch, status):
    # Un pedido cancelado o rechazado no se cobra, ni por link ni desde el panel.
    _insert_user("usr_take_closed", permissions=["payments.take"])
    _make_order(status=status, data={"totals": {"total": 50.0}})
    _forbid_stripe(monkeypatch)

    response = _admin_client("usr_take_closed").post("/api/admin/orders/ord_1/take-payment/")

    assert response.status_code == 409
    assert response.json() == {"error": "Closed orders cannot be paid"}
    assert not Payment.objects.filter(order_id="ord_1").exists()

def _order_locked(queries) -> bool:
    return any(
        'FROM "orders"' in query["sql"] and "FOR UPDATE" in query["sql"] for query in queries
    )


@pytest.mark.django_db
def test_patch_reads_the_order_with_a_row_lock():
    # La comprobación y la escritura tienen que ver la misma fila que ve el
    # webhook, que también la bloquea antes de marcarla pagada.
    _insert_user("usr_patch_lock", permissions=["orders.status"])
    _make_order()
    client = _admin_client("usr_patch_lock")

    with CaptureQueriesContext(connection) as queries:
        response = client.patch("/api/admin/orders/ord_1/", {"status": "PROCESSING"}, format="json")

    assert response.status_code == 200
    assert _order_locked(queries.captured_queries)


@pytest.mark.django_db
def test_delete_reads_the_order_with_a_row_lock():
    _insert_user("usr_delete_lock", permissions=["orders.cancel"])
    _make_order()
    client = _admin_client("usr_delete_lock")

    with CaptureQueriesContext(connection) as queries:
        response = client.delete("/api/admin/orders/ord_1/")

    assert response.status_code == 200
    assert _order_locked(queries.captured_queries)


@pytest.mark.django_db
def test_payment_link_email_escapes_the_order_number_and_the_session_url(monkeypatch, settings):
    settings.RESEND_API_KEY = "re_test_fake"
    _insert_user("usr_link_escape", permissions=["payments.take"])
    _make_order(
        number="<b>O1</b>",
        data={"customer": {"email": "buyer@example.com"}, "totals": {"total": 10.0}},
    )
    client = _admin_client("usr_link_escape")
    monkeypatch.setattr(
        CREATE_SESSION,
        lambda **kwargs: _fake_session(url='https://checkout.stripe.com/pay?a=1&b="x"'),
    )
    resend = install_resend(monkeypatch)

    response = client.post("/api/admin/orders/ord_1/payment-link/")

    assert response.status_code == 200
    html = resend.sent[0]["html"]
    assert "&lt;b&gt;O1&lt;/b&gt;" in html
    assert 'href="https://checkout.stripe.com/pay?a=1&amp;b=&quot;x&quot;"' in html
    assert f'<img src="{email_logo_url()}"' in html
