"""`POST /api/admin/orders/<order_id>/fulfillment/` (permiso `orders.status`).

Mocking: el correo de envío sale por `resend.send_email` falseado con
`tests/fakes.py`; `run_in_background` se ejecuta en línea (parcheado en
`apps.checkout.services.fulfillment`) salvo en el test que prueba que el
request no espera a Resend.

Reglas que se assertean a propósito: el envío va separado de `Order.status`
(avanzar el envío no lo toca), solo avanza un pedido cobrado y no cerrado
(`REFUNDED` total no cuenta), las transiciones van solo hacia adelante con
el salto `UNFULFILLED -> SHIPPED` permitido y corregir la guía estando
`SHIPPED` vuelve a avisar al cliente.
"""
import pytest
from django.utils import timezone

from apps.authentication.utils.background import run_in_background as real_run_in_background
from apps.checkout.models import Order
from apps.common.emails import email_logo_url
from tests.factories import activity_count, create_customer, create_staff_user, session_client
from tests.fakes import SlowResend, forbid_resend, install_resend

BACKGROUND = "apps.checkout.services.fulfillment.run_in_background"


@pytest.fixture(autouse=True)
def _send_emails_inline(monkeypatch):
    monkeypatch.setattr(BACKGROUND, lambda func, *args, **kwargs: func(*args, **kwargs))


@pytest.fixture
def resend(monkeypatch):
    return install_resend(monkeypatch).sent


def _staff(user_id="usr_fulfill", permissions=("orders.status",)):
    create_staff_user(user_id, permissions=list(permissions))
    client, _ = session_client(user_id)
    return client


def _order(
    order_id="ord_ship",
    number="O30001",
    *,
    status="PROCESSING",
    payment_status="PAID",
    data=None,
    **fields,
):
    now = timezone.now()
    return Order.objects.create(
        id=order_id,
        number=number,
        status=status,
        payment_status=payment_status,
        data=data if data is not None else {"customer": {"email": "buyer@example.com"}},
        created_at=now,
        updated_at=now,
        **fields,
    )


def _post(client, body, order_id="ord_ship"):
    return client.post(f"/api/admin/orders/{order_id}/fulfillment/", body, format="json")


def _ship(client, carrier="UPS", tracking="1Z999AA10123456784", order_id="ord_ship"):
    return _post(
        client,
        {"status": "SHIPPED", "carrier": carrier, "trackingNumber": tracking},
        order_id=order_id,
    )


# --- permisos -------------------------------------------------------------


@pytest.mark.django_db
def test_fulfillment_returns_403_without_orders_status():
    client = _staff(permissions=["orders.view"])
    _order()

    response = _post(client, {"status": "PREPARING"})

    assert response.status_code == 403
    assert "error" in response.json()
    assert Order.objects.get(pk="ord_ship").fulfillment_status == "UNFULFILLED"


@pytest.mark.django_db
def test_fulfillment_returns_403_for_a_customer_session():
    from tests.factories import create_user

    create_user("usr_customer")
    client, _ = session_client("usr_customer")
    _order()

    response = _post(client, {"status": "PREPARING"})

    assert response.status_code == 403


@pytest.mark.django_db
def test_fulfillment_returns_404_for_an_unknown_order():
    client = _staff()

    response = _post(client, {"status": "PREPARING"}, order_id="missing")

    assert response.status_code == 404
    assert response.json() == {"error": "Order not found"}


# --- transiciones válidas ---------------------------------------------------


@pytest.mark.django_db
def test_mark_preparing_moves_forward_without_touching_order_status(resend):
    client = _staff()
    _order()

    response = _post(client, {"status": "PREPARING"})

    assert response.status_code == 200
    body = response.json()
    assert body["fulfillmentStatus"] == "PREPARING"
    assert body["trackingUrl"] is None
    order = Order.objects.get(pk="ord_ship")
    assert order.fulfillment_status == "PREPARING"
    assert order.status == "PROCESSING"
    assert order.shipped_at is None
    assert resend == []


@pytest.mark.django_db
def test_mark_shipped_saves_carrier_tracking_and_shipped_at(resend):
    client = _staff()
    _order(fulfillment_status="PREPARING")

    response = _ship(client, carrier="ups", tracking=" 1Z999AA10123456784 ")

    assert response.status_code == 200
    body = response.json()
    assert body["fulfillmentStatus"] == "SHIPPED"
    assert body["carrier"] == "UPS"
    assert body["trackingNumber"] == "1Z999AA10123456784"
    assert body["trackingUrl"] == "https://www.ups.com/track?tracknum=1Z999AA10123456784"
    assert body["shippedAt"]
    assert body["deliveredAt"] is None
    order = Order.objects.get(pk="ord_ship")
    assert order.fulfillment_status == "SHIPPED"
    assert order.carrier == "UPS"
    assert order.tracking_number == "1Z999AA10123456784"
    assert order.shipped_at is not None


@pytest.mark.django_db
def test_unfulfilled_order_can_skip_straight_to_shipped(resend):
    client = _staff()
    _order()

    response = _ship(client, carrier="USPS", tracking="9400111899223100000000")

    assert response.status_code == 200
    assert Order.objects.get(pk="ord_ship").fulfillment_status == "SHIPPED"


@pytest.mark.django_db
def test_partially_refunded_order_can_still_ship(resend):
    client = _staff()
    _order(payment_status="PARTIALLY_REFUNDED")

    response = _ship(client)

    assert response.status_code == 200


@pytest.mark.django_db
def test_mark_delivered_sets_delivered_at_and_keeps_tracking(resend):
    client = _staff()
    _order(
        fulfillment_status="SHIPPED",
        carrier="FEDEX",
        tracking_number="123456789012",
        shipped_at=timezone.now(),
    )

    response = _post(client, {"status": "DELIVERED"})

    assert response.status_code == 200
    body = response.json()
    assert body["fulfillmentStatus"] == "DELIVERED"
    assert body["deliveredAt"]
    assert body["trackingNumber"] == "123456789012"
    order = Order.objects.get(pk="ord_ship")
    assert order.delivered_at is not None
    assert resend == []


@pytest.mark.django_db
def test_correcting_the_tracking_number_while_shipped_is_allowed_and_audited(resend):
    client = _staff()
    shipped_at = timezone.now()
    _order(
        fulfillment_status="SHIPPED",
        carrier="UPS",
        tracking_number="1ZWRONG",
        shipped_at=shipped_at,
    )

    response = _ship(client, carrier="FEDEX", tracking="123456789012")

    assert response.status_code == 200
    order = Order.objects.get(pk="ord_ship")
    assert order.carrier == "FEDEX"
    assert order.tracking_number == "123456789012"
    # La fecha de despacho es la del primer envío: corregir la guía no la mueve.
    assert order.shipped_at == shipped_at
    assert (
        activity_count(
            action="FULFILLMENT_UPDATED",
            entity_id="ord_ship",
            data__previousTrackingNumber="1ZWRONG",
            data__trackingNumber="123456789012",
        )
        == 1
    )
    assert len(resend) == 1
    assert "123456789012" in resend[0]["html"]


# --- transiciones inválidas -------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("current", "target", "message"),
    [
        ("SHIPPED", "PREPARING", "Cannot move fulfillment from SHIPPED to PREPARING"),
        ("DELIVERED", "SHIPPED", "Cannot move fulfillment from DELIVERED to SHIPPED"),
        ("PREPARING", "UNFULFILLED", "Cannot move fulfillment from PREPARING to UNFULFILLED"),
        ("UNFULFILLED", "DELIVERED", "Cannot move fulfillment from UNFULFILLED to DELIVERED"),
        ("PREPARING", "DELIVERED", "Cannot move fulfillment from PREPARING to DELIVERED"),
        ("PREPARING", "PREPARING", "Fulfillment is already PREPARING"),
        ("DELIVERED", "DELIVERED", "Fulfillment is already DELIVERED"),
    ],
)
def test_invalid_transitions_return_409_and_change_nothing(current, target, message):
    client = _staff()
    _order(fulfillment_status=current, carrier="UPS", tracking_number="1Z1")
    body = {"status": target}
    if target == "SHIPPED":
        body.update({"carrier": "UPS", "trackingNumber": "1Z2"})

    response = _post(client, body)

    assert response.status_code == 409
    assert response.json() == {"error": message}
    assert Order.objects.get(pk="ord_ship").fulfillment_status == current
    assert activity_count(action="FULFILLMENT_UPDATED") == 0


@pytest.mark.django_db
def test_reshipping_with_the_same_tracking_number_is_a_conflict(monkeypatch):
    forbid_resend(monkeypatch)
    client = _staff()
    _order(fulfillment_status="SHIPPED", carrier="UPS", tracking_number="1Z1")

    response = _ship(client, carrier="UPS", tracking="1Z1")

    assert response.status_code == 409
    assert response.json() == {"error": "Order already shipped with this tracking number"}


@pytest.mark.django_db
@pytest.mark.parametrize("payment_status", ["UNPAID", "FAILED", "REFUNDED"])
def test_unpaid_or_fully_refunded_orders_cannot_be_fulfilled(monkeypatch, payment_status):
    forbid_resend(monkeypatch)
    client = _staff()
    _order(payment_status=payment_status)

    response = _ship(client)

    assert response.status_code == 409
    assert response.json() == {"error": "Only paid orders can be fulfilled"}
    assert Order.objects.get(pk="ord_ship").fulfillment_status == "UNFULFILLED"


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["CANCELLED", "REJECTED"])
def test_closed_orders_cannot_be_fulfilled(monkeypatch, status):
    forbid_resend(monkeypatch)
    client = _staff()
    _order(status=status)

    response = _post(client, {"status": "PREPARING"})

    assert response.status_code == 409
    assert response.json() == {"error": "Closed orders cannot be fulfilled"}


# --- datos inválidos ----------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({}, "Invalid fulfillment status"),
        ({"status": "LOST"}, "Invalid fulfillment status"),
        ({"status": "SHIPPED", "carrier": "UPS"}, "Tracking number is required to ship an order"),
        (
            {"status": "SHIPPED", "trackingNumber": "1Z1"},
            "Carrier must be one of UPS, FEDEX, USPS, OTHER",
        ),
        (
            {"status": "SHIPPED", "carrier": "DHL", "trackingNumber": "1Z1"},
            "Carrier must be one of UPS, FEDEX, USPS, OTHER",
        ),
        (
            {"status": "SHIPPED", "carrier": "UPS", "trackingNumber": "1Z 1"},
            "Tracking number must be 1 to 64 letters, digits or hyphens",
        ),
        (
            {"status": "SHIPPED", "carrier": "UPS", "trackingNumber": "<b>1</b>"},
            "Tracking number must be 1 to 64 letters, digits or hyphens",
        ),
        (
            {"status": "SHIPPED", "carrier": "UPS", "trackingNumber": "A" * 65},
            "Tracking number must be 1 to 64 letters, digits or hyphens",
        ),
        (
            {"status": "SHIPPED", "carrier": "UPS", "trackingNumber": 12345},
            "Tracking number must be 1 to 64 letters, digits or hyphens",
        ),
        (
            {"status": "PREPARING", "carrier": "UPS"},
            "Carrier and tracking number can only be set when marking an order SHIPPED",
        ),
    ],
)
def test_invalid_payloads_return_400(monkeypatch, body, message):
    forbid_resend(monkeypatch)
    client = _staff()
    _order()

    response = _post(client, body)

    assert response.status_code == 400
    assert response.json() == {"error": message}
    assert Order.objects.get(pk="ord_ship").fulfillment_status == "UNFULFILLED"


@pytest.mark.django_db
def test_invalid_payload_is_rejected_before_looking_up_the_order():
    client = _staff()

    response = _post(client, {"status": "SHIPPED"}, order_id="missing")

    assert response.status_code == 400


# --- bitácora -------------------------------------------------------------------


@pytest.mark.django_db
def test_every_update_is_audited_with_previous_and_new_status(resend):
    client = _staff()
    _order()

    _post(client, {"status": "PREPARING"})
    _ship(client, carrier="USPS", tracking="9400111899223100000000")

    assert (
        activity_count(
            action="FULFILLMENT_UPDATED",
            entity_type="ORDER",
            entity_id="ord_ship",
            actor_id="usr_fulfill@example.com",
            data__previousStatus="UNFULFILLED",
            data__status="PREPARING",
        )
        == 1
    )
    assert (
        activity_count(
            action="FULFILLMENT_UPDATED",
            entity_id="ord_ship",
            data__previousStatus="PREPARING",
            data__status="SHIPPED",
            data__carrier="USPS",
            data__trackingNumber="9400111899223100000000",
        )
        == 1
    )


# --- correo de envío ------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("carrier", "tracking", "url", "label"),
    [
        (
            "UPS",
            "1Z999AA10123456784",
            "https://www.ups.com/track?tracknum=1Z999AA10123456784",
            "UPS",
        ),
        (
            "FEDEX",
            "123456789012",
            "https://www.fedex.com/fedextrack/?trknbr=123456789012",
            "FedEx",
        ),
        (
            "USPS",
            "9400111899223100000000",
            "https://tools.usps.com/go/TrackConfirmAction?tLabels=9400111899223100000000",
            "USPS",
        ),
    ],
)
def test_shipped_email_links_to_the_carrier_tracking_page(resend, carrier, tracking, url, label):
    client = _staff()
    _order()

    _ship(client, carrier=carrier, tracking=tracking)

    assert len(resend) == 1
    email = resend[0]
    assert email["to"] == ["buyer@example.com"]
    assert email["subject"] == "Your TorqueTrack order O30001 has shipped"
    assert f'href="{url}"' in email["html"]
    assert label in email["html"]
    assert tracking in email["html"]


@pytest.mark.django_db
def test_shipped_email_for_other_carrier_has_no_tracking_link(resend):
    client = _staff()
    _order()

    response = _ship(client, carrier="OTHER", tracking="LOCAL-778")

    assert response.json()["trackingUrl"] is None
    assert len(resend) == 1
    assert "LOCAL-778" in resend[0]["html"]
    assert "href" not in resend[0]["html"]


@pytest.mark.django_db
def test_shipped_email_escapes_customer_data(resend):
    client = _staff()
    _order(data={"customer": {"email": "buyer@example.com", "name": "<script>x</script>"}})

    _ship(client)

    html = resend[0]["html"]
    assert "<script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert f'<img src="{email_logo_url()}"' in html


@pytest.mark.django_db
def test_shipped_email_falls_back_to_the_customer_profile_email(resend):
    client = _staff()
    create_customer("C_SHIP", email="profile@example.com")
    _order(data={}, customer_id="C_SHIP")

    _ship(client)

    assert resend[0]["to"] == ["profile@example.com"]


@pytest.mark.django_db
def test_order_without_email_ships_without_sending(monkeypatch):
    forbid_resend(monkeypatch)
    client = _staff()
    _order(data={})

    response = _ship(client)

    assert response.status_code == 200


@pytest.mark.django_db
def test_shipping_without_resend_configured_only_logs(settings, caplog):
    settings.RESEND_API_KEY = ""
    client = _staff()
    _order()

    with caplog.at_level("WARNING", logger="apps.checkout.services.fulfillment"):
        response = _ship(client)

    assert response.status_code == 200
    assert "O30001" in caplog.text
    assert "buyer@example.com" not in caplog.text


@pytest.mark.django_db(transaction=True)
def test_shipped_email_is_sent_outside_the_request(monkeypatch):
    monkeypatch.setattr(BACKGROUND, real_run_in_background)
    fake = install_resend(monkeypatch, SlowResend())
    client = _staff()
    _order()

    try:
        response = _ship(client)
        assert response.status_code == 200
        assert fake.sent == []
    finally:
        fake.release.set()
    assert fake.delivered.wait(5)
    assert fake.sent[0]["subject"] == "Your TorqueTrack order O30001 has shipped"
