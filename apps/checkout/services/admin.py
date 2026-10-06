"""Reglas de negocio de los pedidos en el panel de administración."""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from django.utils.html import format_html

from apps.audit.services import record_activity
from apps.checkout.models import (
    CoreStatus,
    Order,
    OrderPaymentStatus,
    OrderStatus,
    Payment,
    Refund,
    ReturnStatus,
)
from apps.checkout.services.payments import (
    CHARGED_PAYMENT_STATUSES,
    CLOSED_ORDER_STATUSES,
    STRIPE_REQUEST_FAILED,
    cancel_pending_payments,
    start_stripe_payment,
)
from apps.checkout.services.refunds import order_refund_summary, serialize_refund
from apps.common.business_day import store_today_bounds
from apps.common.emails import branded_email_html
from apps.common.errors import error_payload
from apps.common.numbers import money, money_decimal
from apps.integrations.email import resend
from apps.integrations.exceptions import ProviderError

logger = logging.getLogger(__name__)

# El panel no salta estados. El cobro (`PENDING_PAYMENT` → `OPEN`), la
# expiración sin pago (`CANCELLED`) y el reembolso no pasan por aquí: el
# reembolso solo cambia `payment_status`, y el envío vive en `fulfillment`.
ORDER_STATUS_TRANSITIONS = {
    OrderStatus.PENDING_PAYMENT: {OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.OPEN: {OrderStatus.PROCESSING, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.PROCESSING: {OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
}


# Ids de Stripe: verlos exige `payments.transaction_id`, no `orders.view`.
def _serialize_order(order: Order, can_view_transaction_ids: bool) -> dict:
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

    payments = list(order.payments.all())
    refunds = order_refund_summary(order, payments)
    extra = {}
    if isinstance(data.get("payment"), dict) and not can_view_transaction_ids:
        extra["payment"] = {k: v for k, v in data["payment"].items() if k != "paymentIntent"}

    return {
        **data,
        **extra,
        "id": order.pk,
        "number": order.number,
        "status": order.status,
        "paymentStatus": order.payment_status,
        "createdAt": order.created_at,
        "customer": customer,
        "payments": [
            _serialize_payment(payment, can_view_transaction_ids) for payment in payments
        ],
        "refunds": [
            serialize_refund(refund, can_view_transaction_ids) for refund in refunds["refunds"]
        ],
        "amountRefunded": money(refunds["amountRefunded"]),
        "refundableAmount": money(refunds["refundableAmount"]),
        **order.fulfillment_summary(),
    }


def _serialize_payment(payment: Payment, can_view_transaction_ids: bool) -> dict:
    data = payment.data or {}
    admin_link = "ADMIN_PAYMENT_LINK" if data.get("adminGenerated") else ""
    row = {
        "id": payment.pk,
        "provider": payment.provider,
        "status": payment.status,
        "amount": money(payment.amount),
        "source": data.get("source") or admin_link,
        "createdAt": payment.created_at,
    }
    if can_view_transaction_ids:
        row["providerId"] = payment.provider_id
        row["paymentIntent"] = data.get("payment_intent")
    return row


ORDER_DATE_FILTERS = ("today",)
INVALID_ORDER_DATE_FILTER = "date must be today"


def list_admin_orders(
    can_view_transaction_ids: bool = False, date: str | None = None
) -> tuple[list[dict], int] | dict:
    """Todos los pedidos, o con `date="today"` solo los creados hoy en la zona
    de la tienda (`settings.STORE_TIME_ZONE`), el mismo día de "Sales today"."""
    if date and date not in ORDER_DATE_FILTERS:
        return error_payload(INVALID_ORDER_DATE_FILTER, "date", status=400)
    orders = (
        Order.objects.select_related("customer")
        .prefetch_related(
            Prefetch(
                "payments",
                queryset=Payment.objects.order_by("created_at").prefetch_related(
                    Prefetch("refunds", queryset=Refund.objects.order_by("created_at"))
                ),
            )
        )
        .order_by("created_at")
    )
    if date == "today":
        start, end = store_today_bounds()
        orders = orders.filter(created_at__gte=start, created_at__lt=end)
    return [_serialize_order(order, can_view_transaction_ids) for order in orders], 200


def _workflow_patch(workflow: dict, actor_email: str) -> dict:
    """`{"patch": ...}` validado, o `{"error": ..., "status": 400}`."""
    patch: dict = {}

    core_case = workflow.get("coreCase")
    if core_case:
        core_status = str(core_case.get("status") or "").upper()
        if core_status not in CoreStatus.values:
            return {"error": "Invalid core status", "status": 400}
        patch["coreCase"] = {**core_case, "status": core_status, "updatedBy": actor_email}

    return_case = workflow.get("returnCase")
    if return_case:
        return_status = str(return_case.get("status") or "").upper()
        if return_status not in ReturnStatus.values:
            return {"error": "Invalid return status", "status": 400}
        patch["returnCase"] = {**return_case, "status": return_status, "updatedBy": actor_email}

    if not patch:
        return {"error": "No workflow changes supplied", "status": 400}
    return {"patch": patch}


def patch_admin_order(order_id: str, payload: dict, actor_email: str) -> dict:
    """`status` y `workflow` se validan juntos y se aplican en la misma
    transacción: o cambian los dos o ninguno."""
    status = str(payload["status"]).upper() if payload.get("status") else None
    if status is not None and status not in OrderStatus.values:
        return {"error": "Invalid order status", "status": 400}

    workflow = payload.get("workflow")
    patch = None
    if isinstance(workflow, dict):
        result = _workflow_patch(workflow, actor_email)
        if "error" in result:
            return result
        patch = result["patch"]

    if status is None and patch is None:
        return {"error": "No supported changes supplied", "status": 400}

    with transaction.atomic():
        # Misma fila bloqueada que usa el webhook: un pago que llega a la vez
        # no se pisa con este cambio.
        order = Order.objects.select_for_update().filter(pk=order_id).first()
        if order is None:
            return {"error": "Order not found", "status": 404}
        if status is not None and status != order.status:
            allowed = ORDER_STATUS_TRANSITIONS.get(order.status, set())
            if status not in allowed:
                return {
                    "error": f"Cannot move order from {order.status} to {status}",
                    "status": 409,
                }
        fields = ["updated_at"]
        if status is not None:
            order.status = status
            fields.append("status")
        if patch is not None:
            order.data = {**(order.data or {}), **patch}
            fields.append("data")
        order.updated_at = timezone.now()
        order.save(update_fields=fields)
        if status in CLOSED_ORDER_STATUSES:
            cancel_pending_payments(order, f"ORDER_{status}")

    response = {"ok": True}
    if status is not None:
        record_activity(
            actor=actor_email,
            action="ORDER_STATUS_CHANGED",
            entity_type="ORDER",
            entity_id=order.pk,
            data={"number": order.number, "status": status, "paymentStatus": order.payment_status},
        )
        response["status"] = status
    if patch is not None:
        record_activity(
            actor=actor_email,
            action="ORDER_WORKFLOW_UPDATED",
            entity_type="ORDER",
            entity_id=order.pk,
            data={"number": order.number, **patch},
        )
        response.update(patch)
    return response


def delete_admin_order(order_id: str, actor_email: str) -> dict:
    with transaction.atomic():
        # `payment_status` se lee de la fila bloqueada: el webhook la bloquea
        # igual antes de marcarla pagada, así que nunca se borra un pedido
        # que se está cobrando en ese momento.
        order = Order.objects.select_for_update().filter(pk=order_id).first()
        if order is None:
            return {"error": "Order not found", "status": 404}

        if order.payment_status != OrderPaymentStatus.UNPAID:
            return {
                "error": "Paid/processed orders cannot be deleted. Cancel or refund them to "
                "preserve payment history.",
                "status": 409,
            }

        number = order.number
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
    if order.payment_status in CHARGED_PAYMENT_STATUSES:
        return {"error": "Order is already paid", "status": 409}
    if order.status in CLOSED_ORDER_STATUSES:
        return {"error": "Closed orders cannot be paid", "status": 409}

    try:
        payment, session = start_stripe_payment(
            order, data={"adminGenerated": True, "source": "ADMIN_PAYMENT_LINK"}
        )
    except ProviderError as exc:
        logger.warning("Stripe payment link for order %s failed: %s", order_id, exc)
        return {"error": STRIPE_REQUEST_FAILED, "status": 502}

    total = money_decimal(payment.amount)
    order.status = OrderStatus.PENDING_PAYMENT
    order.updated_at = timezone.now()
    order.save(update_fields=["status", "updated_at"])

    email = ((order.data or {}).get("customer") or {}).get("email")
    emailed = False
    if email:
        sent = resend.send_email(
            to=email,
            subject=f"TorqueTrack payment link for Order {order.number}",
            html=branded_email_html(
                format_html(
                    "<h2>Order {}</h2>"
                    "<p>Your TorqueTrack order is ready for secure payment.</p>"
                    '<p><a href="{}">Pay securely online</a></p>'
                    "<p>Total: ${}</p>",
                    order.number,
                    session["url"],
                    f"{total}",
                )
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
    if order.payment_status in CHARGED_PAYMENT_STATUSES:
        return {"error": "Order is already paid", "status": 409}
    if order.status in CLOSED_ORDER_STATUSES:
        return {"error": "Closed orders cannot be paid", "status": 409}

    try:
        _, session = start_stripe_payment(
            order, data={"employee": actor_email, "source": "EMPLOYEE_TAKE_PAYMENT"}
        )
    except ProviderError as exc:
        logger.warning("Stripe take-payment for order %s failed: %s", order_id, exc)
        return {"error": STRIPE_REQUEST_FAILED, "status": 502}

    record_activity(
        actor=actor_email,
        action="TAKE_PAYMENT_STARTED",
        entity_type="ORDER",
        entity_id=order_id,
        data={"sessionId": session["id"]},
    )
    return {"ok": True, "url": session["url"]}
