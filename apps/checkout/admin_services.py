"""`admin/orders`, `admin/orders/[id]`, `admin/orders/[id]/payment-link`,
`admin/orders/[id]/take-payment` business rules (task 7.4), near-verbatim
ports of `app/api/admin/orders/route.ts`, `app/api/admin/orders/[id]/
route.ts`, `app/api/admin/orders/[id]/payment-link/route.ts`, and
`app/api/admin/orders/[id]/take-payment/route.ts`.

Reuses `apps.quotes.services.send_email` for the payment-link email
instead of duplicating the Resend REST call a third time (same precedent
as `apps.quotes.admin_services` reusing `apps.checkout.services`).
"""
from __future__ import annotations

from django.utils import timezone

from apps.backoffice.models import ActivityLog
from apps.checkout.models import Order, Payment
from apps.checkout.services import (
    create_stripe_checkout_session,
    js_number_or,
    money,
    random_id,
)

ORDER_STATUSES = ["OPEN", "PENDING_PAYMENT", "PROCESSING", "COMPLETED", "CANCELLED", "REJECTED"]
CORE_STATUSES = [
    "AWAITING CORE", "IN TRANSIT", "RECEIVED", "INSPECTING", "ACCEPTED", "REJECTED", "REFUNDED",
]
RETURN_STATUSES = [
    "REQUESTED", "APPROVED", "IN TRANSIT", "RECEIVED", "INSPECTING", "REFUNDED", "REJECTED",
]


def _serialize_order(order: Order) -> dict:
    data = order.data or {}
    if order.customer_id and order.customer is not None:
        customer = {
            **(order.customer.data or {}),
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
    }


def list_admin_orders() -> list[dict]:
    orders = Order.objects.select_related("customer").order_by("created_at")
    return [_serialize_order(order) for order in orders]


def _update_order_status(order: Order, raw_status: str, actor_username: str) -> dict:
    status = raw_status.upper()
    if status not in ORDER_STATUSES:
        return {"error": "Invalid order status", "status": 400}

    order.status = status
    order.updated_at = timezone.now()
    order.save(update_fields=["status", "updated_at"])
    ActivityLog.objects.create(
        actor_id=actor_username,
        action="ORDER_STATUS_CHANGED",
        entity_type="ORDER",
        entity_id=order.pk,
        data={"number": order.number, "status": status, "paymentStatus": order.payment_status},
        created_at=timezone.now(),
    )
    return {"ok": True, "status": status}


def _update_order_workflow(order: Order, workflow: dict, actor_username: str) -> dict:
    patch: dict = {}

    core_case = workflow.get("coreCase")
    if core_case:
        core_status = str(core_case.get("status") or "").upper()
        if core_status not in CORE_STATUSES:
            return {"error": "Invalid core status", "status": 400}
        patch["coreCase"] = {**core_case, "status": core_status, "updatedBy": actor_username}

    return_case = workflow.get("returnCase")
    if return_case:
        return_status = str(return_case.get("status") or "").upper()
        if return_status not in RETURN_STATUSES:
            return {"error": "Invalid return status", "status": 400}
        patch["returnCase"] = {**return_case, "status": return_status, "updatedBy": actor_username}

    if not patch:
        return {"error": "No workflow changes supplied", "status": 400}

    order.data = {**(order.data or {}), **patch}
    order.updated_at = timezone.now()
    order.save(update_fields=["data", "updated_at"])
    ActivityLog.objects.create(
        actor_id=actor_username,
        action="ORDER_WORKFLOW_UPDATED",
        entity_type="ORDER",
        entity_id=order.pk,
        data={"number": order.number, **patch},
        created_at=timezone.now(),
    )
    return {"ok": True, **patch}


def patch_admin_order(order_id: str, payload: dict, actor_username: str) -> dict:
    order = Order.objects.filter(pk=order_id).first()
    if order is None:
        return {"error": "Order not found", "status": 404}

    if payload.get("status"):
        return _update_order_status(order, str(payload["status"]), actor_username)

    workflow = payload.get("workflow")
    if isinstance(workflow, dict):
        return _update_order_workflow(order, workflow, actor_username)

    return {"error": "No supported changes supplied", "status": 400}


def delete_admin_order(order_id: str, actor_username: str) -> dict:
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
    Payment.objects.filter(order=order).delete()
    order.delete()
    ActivityLog.objects.create(
        actor_id=actor_username,
        action="UNPAID_ORDER_DELETED",
        entity_type="ORDER",
        entity_id=order_id,
        data={"number": number},
        created_at=timezone.now(),
    )
    return {"ok": True}


def create_admin_payment_link(order_id: str) -> dict:
    """`POST /api/admin/orders/[id]/payment-link` — sets the order to
    `PENDING_PAYMENT` and emails the customer a pay link when an email is
    on file."""
    from apps.quotes.services import send_email

    order = Order.objects.filter(pk=order_id).first()
    if order is None:
        return {"error": "Order not found", "status": 404}
    if order.payment_status == "PAID":
        return {"error": "Order is already paid", "status": 409}

    try:
        session = create_stripe_checkout_session(
            {"id": order.pk, "number": order.number, **(order.data or {})}
        )
    except Exception as exc:  # noqa: BLE001 - mirrors the route's `catch(e:any)`
        return {"error": str(exc) or "Could not create payment link", "status": 502}

    total = money(((order.data or {}).get("totals") or {}).get("total"))
    Payment.objects.create(
        id=random_id("PAY"),
        order=order,
        provider="stripe",
        provider_id=session["id"],
        status="PENDING",
        amount=total,
        data={"sessionId": session["id"], "adminGenerated": True},
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )
    order.status = "PENDING_PAYMENT"
    order.updated_at = timezone.now()
    order.save(update_fields=["status", "updated_at"])

    email = ((order.data or {}).get("customer") or {}).get("email")
    emailed = False
    if email:
        sent = send_email(
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


def take_admin_payment(order_id: str, actor_username: str) -> dict:
    """`POST /api/admin/orders/[id]/take-payment` — unlike payment-link,
    does NOT change `order.status` and logs `TAKE_PAYMENT_STARTED` instead
    of emailing the customer."""
    order = Order.objects.filter(pk=order_id).first()
    if order is None:
        return {"error": "Order not found", "status": 404}
    if order.payment_status == "PAID":
        return {"error": "Order is already paid", "status": 409}

    try:
        session = create_stripe_checkout_session(
            {**(order.data or {}), "id": order.pk, "number": order.number}
        )
    except Exception as exc:  # noqa: BLE001 - mirrors the route's `catch(e:any)`
        return {"error": str(exc) or "Could not start secure payment", "status": 502}

    total = js_number_or(((order.data or {}).get("totals") or {}).get("total"), 0.0)
    Payment.objects.create(
        id=random_id("PAY"),
        order=order,
        provider="stripe",
        provider_id=session["id"],
        status="PENDING",
        amount=total,
        data={
            "sessionId": session["id"],
            "employee": actor_username,
            "source": "EMPLOYEE_TAKE_PAYMENT",
        },
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )
    ActivityLog.objects.create(
        actor_id=actor_username,
        action="TAKE_PAYMENT_STARTED",
        entity_type="ORDER",
        entity_id=order_id,
        data={"sessionId": session["id"]},
        created_at=timezone.now(),
    )
    return {"ok": True, "url": session["url"]}
