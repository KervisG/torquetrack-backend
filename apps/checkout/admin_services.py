"""Reglas de negocio de los pedidos en el panel de administración."""
from __future__ import annotations

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from apps.audit.services import record_activity
from apps.checkout.models import Order, Payment
from apps.checkout.services import cancel_pending_payments, start_stripe_payment
from apps.integrations.email import resend
from apps.integrations.exceptions import ProviderError

ORDER_STATUSES = ["OPEN", "PENDING_PAYMENT", "PROCESSING", "COMPLETED", "CANCELLED", "REJECTED"]
# Estados en los que el pedido ya no se va a cobrar ni despachar.
CLOSED_ORDER_STATUSES = {"CANCELLED", "REJECTED"}
CORE_STATUSES = [
    "AWAITING CORE", "IN TRANSIT", "RECEIVED", "INSPECTING", "ACCEPTED", "REJECTED", "REFUNDED",
]
RETURN_STATUSES = [
    "REQUESTED", "APPROVED", "IN TRANSIT", "RECEIVED", "INSPECTING", "REFUNDED", "REJECTED",
]


def _serialize_order(order: Order) -> dict:
    data = order.data or {}
    if order.customer_id and order.customer is not None:
        # El snapshot del pedido gana sobre el perfil: un checkout invitado ya
        # no reescribe el perfil, así que su dirección de envío vive solo aquí.
        customer = {
            **(order.customer.data or {}),
            **(data.get("customer") or {}),
            "id": order.customer_id,
            "email": order.customer.email,
        }
    else:
        customer = data.get("customer")

    return {
        **data,
        "id": order.pk,
        "number": order.number,
        "status": order.status,
        "paymentStatus": order.payment_status,
        "createdAt": order.created_at,
        "customer": customer,
        "payments": [_serialize_payment(payment) for payment in order.payments.all()],
    }


def _serialize_payment(payment: Payment) -> dict:
    """Sin `provider_id`: ver el id de la transacción exige
    `payments.transaction_id`, no `orders.view`."""
    data = payment.data or {}
    admin_link = "ADMIN_PAYMENT_LINK" if data.get("adminGenerated") else ""
    return {
        "id": payment.pk,
        "provider": payment.provider,
        "status": payment.status,
        "amount": float(payment.amount),
        "source": data.get("source") or admin_link,
        "createdAt": payment.created_at,
    }


def list_admin_orders() -> list[dict]:
    orders = (
        Order.objects.select_related("customer")
        .prefetch_related(Prefetch("payments", queryset=Payment.objects.order_by("created_at")))
        .order_by("created_at")
    )
    return [_serialize_order(order) for order in orders]


def _update_order_status(order: Order, raw_status: str, actor_email: str) -> dict:
    status = raw_status.upper()
    if status not in ORDER_STATUSES:
        return {"error": "Invalid order status", "status": 400}

    with transaction.atomic():
        order.status = status
        order.updated_at = timezone.now()
        order.save(update_fields=["status", "updated_at"])
        if status in CLOSED_ORDER_STATUSES:
            cancel_pending_payments(order, f"ORDER_{status}")
    record_activity(
        actor=actor_email,
        action="ORDER_STATUS_CHANGED",
        entity_type="ORDER",
        entity_id=order.pk,
        data={"number": order.number, "status": status, "paymentStatus": order.payment_status},
    )
    return {"ok": True, "status": status}


def _update_order_workflow(order: Order, workflow: dict, actor_email: str) -> dict:
    patch: dict = {}

    core_case = workflow.get("coreCase")
    if core_case:
        core_status = str(core_case.get("status") or "").upper()
        if core_status not in CORE_STATUSES:
            return {"error": "Invalid core status", "status": 400}
        patch["coreCase"] = {**core_case, "status": core_status, "updatedBy": actor_email}

    return_case = workflow.get("returnCase")
    if return_case:
        return_status = str(return_case.get("status") or "").upper()
        if return_status not in RETURN_STATUSES:
            return {"error": "Invalid return status", "status": 400}
        patch["returnCase"] = {**return_case, "status": return_status, "updatedBy": actor_email}

    if not patch:
        return {"error": "No workflow changes supplied", "status": 400}

    order.data = {**(order.data or {}), **patch}
    order.updated_at = timezone.now()
    order.save(update_fields=["data", "updated_at"])
    record_activity(
        actor=actor_email,
        action="ORDER_WORKFLOW_UPDATED",
        entity_type="ORDER",
        entity_id=order.pk,
        data={"number": order.number, **patch},
    )
    return {"ok": True, **patch}


def patch_admin_order(order_id: str, payload: dict, actor_email: str) -> dict:
    order = Order.objects.filter(pk=order_id).first()
    if order is None:
        return {"error": "Order not found", "status": 404}

    if payload.get("status"):
        return _update_order_status(order, str(payload["status"]), actor_email)

    workflow = payload.get("workflow")
    if isinstance(workflow, dict):
        return _update_order_workflow(order, workflow, actor_email)

    return {"error": "No supported changes supplied", "status": 400}


def delete_admin_order(order_id: str, actor_email: str) -> dict:
    order = Order.objects.filter(pk=order_id).first()
    if order is None:
        return {"error": "Order not found", "status": 404}

    if order.payment_status != "UNPAID":
        return {
            "error": "Paid/processed orders cannot be deleted. Cancel or refund them to "
            "preserve payment history.",
            "status": 409,
        }

    number = order.number
    with transaction.atomic():
        # Se cancelan antes de borrar para expirar sus sesiones: una sesión
        # viva sin `Payment` cobraría un pedido que ya no existe.
        cancel_pending_payments(order, "ORDER_DELETED")
        Payment.objects.filter(order=order).delete()
        order.delete()
    record_activity(
        actor=actor_email,
        action="UNPAID_ORDER_DELETED",
        entity_type="ORDER",
        entity_id=order_id,
        data={"number": number},
    )
    return {"ok": True}


def create_admin_payment_link(order_id: str) -> dict:
    order = Order.objects.filter(pk=order_id).first()
    if order is None:
        return {"error": "Order not found", "status": 404}
    if order.payment_status == "PAID":
        return {"error": "Order is already paid", "status": 409}

    try:
        payment, session = start_stripe_payment(
            order, data={"adminGenerated": True, "source": "ADMIN_PAYMENT_LINK"}
        )
    except ProviderError as exc:
        return {"error": str(exc) or "Could not create payment link", "status": 502}

    total = float(payment.amount)
    order.status = "PENDING_PAYMENT"
    order.updated_at = timezone.now()
    order.save(update_fields=["status", "updated_at"])

    email = ((order.data or {}).get("customer") or {}).get("email")
    emailed = False
    if email:
        sent = resend.send_email(
            to=email,
            subject=f"TorqueTrack payment link for Order {order.number}",
            html=(
                f"<h2>Order {order.number}</h2>"
                "<p>Your TorqueTrack order is ready for secure payment.</p>"
                f'<p><a href="{session["url"]}">Pay securely online</a></p>'
                f"<p>Total: ${total:.2f}</p>"
            ),
        )
        emailed = sent["sent"]

    return {"ok": True, "url": session["url"], "emailed": emailed}


def take_admin_payment(order_id: str, actor_email: str) -> dict:
    """A diferencia del link de pago, no cambia `order.status` ni envía email
    al cliente."""
    order = Order.objects.filter(pk=order_id).first()
    if order is None:
        return {"error": "Order not found", "status": 404}
    if order.payment_status == "PAID":
        return {"error": "Order is already paid", "status": 409}

    try:
        _, session = start_stripe_payment(
            order, data={"employee": actor_email, "source": "EMPLOYEE_TAKE_PAYMENT"}
        )
    except ProviderError as exc:
        return {"error": str(exc) or "Could not start secure payment", "status": 502}

    record_activity(
        actor=actor_email,
        action="TAKE_PAYMENT_STARTED",
        entity_type="ORDER",
        entity_id=order_id,
        data={"sessionId": session["id"]},
    )
    return {"ok": True, "url": session["url"]}
