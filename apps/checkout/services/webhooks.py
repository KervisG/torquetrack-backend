"""Conciliación de los eventos del webhook de Authorize.net.

El payload del webhook trae poco y no se usa como verdad: cada evento se
concilia releyendo la transacción con `getTransactionDetails` (tipo, estado,
monto, `invoiceNumber`, tarjeta). El `invoiceNumber` de un cobro es el id del
`Payment`; el de un reembolso del panel es el id del `Refund`.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity
from apps.checkout.models import (
    CoreStatus,
    OrderPaymentStatus,
    OrderStatus,
    Payment,
    PaymentStatus,
)
from apps.checkout.services.payments import (
    CHARGED_PAYMENT_STATUSES,
    CLOSED_ORDER_STATUSES,
    PROVIDER,
    PROVIDER_ACTOR,
    cancel_pending_payment,
    lock_order_and_payment,
)
from apps.checkout.services.refunds import sync_provider_refund, sync_provider_void
from apps.checkout.services.workflow_emails import notify_core_opened
from apps.common.numbers import money
from apps.integrations.payments import authorize_net

logger = logging.getLogger(__name__)

# `transactionStatus` de un cobro aprobado y capturado.
CAPTURED_STATUSES = ("capturedPendingSettlement", "settledSuccessfully")
# Retenido por el filtro de fraude (AFDS): no está cobrado todavía.
HELD_STATUSES = ("FDSPendingReview", "FDSAuthorizedPendingReview", "underReview")
CHARGE_TYPES = ("authCaptureTransaction",)


def _details(trans_id, event_name: str) -> dict | None:
    """Relee la transacción. Un fallo de red lanza `ProviderError` para que la
    view responda 5xx y Authorize.net reintente."""
    if not trans_id:
        logger.warning("Authorize.net %s without transaction id", event_name)
        return None
    return authorize_net.get_transaction(str(trans_id))


def _charge_payment(details: dict, event_name: str) -> Payment | None:
    """`Payment` del cobro, o `None` si la transacción no es nuestra."""
    invoice = details.get("invoiceNumber")
    payment = (
        Payment.objects.filter(provider=PROVIDER, pk=invoice).first() if invoice else None
    )
    if payment is None or payment.order_id is None:
        # Se responde 200 igual: reintentar no va a hacer aparecer el pago.
        logger.warning(
            "Authorize.net %s for transaction %s (invoice %s) matches no payment",
            event_name,
            details.get("id"),
            invoice,
        )
        return None
    return payment


def _paid_payment(trans_id, event_name: str) -> Payment | None:
    """`Payment` ya cobrado por la transacción `trans_id`."""
    payment = (
        Payment.objects.filter(provider=PROVIDER, provider_id=str(trans_id)).first()
        if trans_id
        else None
    )
    if payment is None or payment.order_id is None:
        logger.warning(
            "Authorize.net %s for transaction %s matches no payment", event_name, trans_id
        )
        return None
    return payment


def reconcile_charge(trans_id) -> None:
    """`authcapture.created` y `fraud.approved`.

    Marca PAID el pago de ESA transacción y el pedido, y cancela los demás
    pagos pendientes del pedido. Es idempotente: un reenvío del mismo evento,
    o dos eventos concurrentes, registran una sola vez. Si el pedido ya estaba
    pagado por otro cobro, el cobro igual existe: el pago queda PAID y la
    bitácora lo marca para reembolso. Lo mismo con un pedido cancelado o
    rechazado, que además conserva su estado (`PAYMENT_ON_CLOSED_ORDER`).
    Un cobro retenido por fraude solo se marca (`reconcile_fraud_held`).
    """
    details = _details(trans_id, "charge")
    if details is None or details.get("type") not in CHARGE_TYPES:
        return
    if details.get("status") in HELD_STATUSES:
        _flag_fraud_hold(details)
        return
    if details.get("status") not in CAPTURED_STATUSES:
        # Un rechazo no cierra el pago: el cliente puede reintentar en el form.
        logger.info(
            "Authorize.net transaction %s is %s; nothing to reconcile",
            details.get("id"),
            details.get("status"),
        )
        return
    payment = _charge_payment(details, "charge")
    # Un pago reembolsado sigue cobrado: un reenvío del evento no lo repaga.
    if payment is None or payment.status in CHARGED_PAYMENT_STATUSES:
        return

    tid = details["id"]
    now = timezone.now()
    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        if order is None or payment.status in CHARGED_PAYMENT_STATUSES:
            return

        if details.get("amount") != payment.amount:
            # Cobrar otro monto no salda el pedido: queda pendiente para que
            # el staff lo revise. Se responde 200 igual porque un reintento
            # no lo resuelve.
            logger.warning(
                "Authorize.net transaction %s charged %s; payment %s expects %s",
                tid,
                details.get("amount"),
                payment.pk,
                payment.amount,
            )
            record_activity(
                actor=PROVIDER_ACTOR,
                action="PAYMENT_AMOUNT_MISMATCH",
                entity_type="ORDER",
                entity_id=order.pk,
                data={
                    "transactionId": tid,
                    "paymentId": payment.pk,
                    "amountCharged": money(details.get("amount") or 0),
                    "expectedAmount": money(payment.amount),
                },
            )
            return

        payment.status = PaymentStatus.PAID
        payment.provider_id = tid
        payment.paid_at = now
        payment.updated_at = now
        payment.data = {
            **(payment.data or {}),
            "transactionId": tid,
            "transactionStatus": details.get("status"),
            "customer_email": details.get("email"),
            "brand": details.get("cardType"),
            "last4": details.get("last4"),
        }
        payment.save(update_fields=["status", "provider_id", "paid_at", "updated_at", "data"])

        activity = {
            "transactionId": tid,
            "amountCharged": money(payment.amount),
            "brand": details.get("cardType"),
            "last4": details.get("last4"),
        }
        if order.payment_status in CHARGED_PAYMENT_STATUSES:
            record_activity(
                actor=PROVIDER_ACTOR,
                action="DUPLICATE_PAYMENT_RECEIVED",
                entity_type="ORDER",
                entity_id=order.pk,
                data={**activity, "paymentId": payment.pk},
            )
            return

        # Un pedido cancelado o rechazado no se reabre: el cobro queda
        # registrado para que el staff lo reembolse.
        closed = order.status in CLOSED_ORDER_STATUSES
        order_data = order.data or {}
        paid_patch = {
            "payment": {
                "provider": PROVIDER,
                "brand": details.get("cardType"),
                "last4": details.get("last4"),
                "transactionId": tid,
                "paidAt": now.isoformat(),
            }
        }
        core_amount = money((order_data.get("totals") or {}).get("core"))
        if core_amount > 0 and not order_data.get("coreCase") and not closed:
            paid_patch["coreCase"] = {
                "status": CoreStatus.AWAITING_CORE,
                "amount": core_amount,
                "createdAt": now.isoformat(),
                "createdBy": PROVIDER_ACTOR,
            }
        if not closed:
            order.status = OrderStatus.OPEN
        order.payment_status = OrderPaymentStatus.PAID
        order.updated_at = now
        order.data = {**order_data, **paid_patch}
        order.save(update_fields=["status", "payment_status", "updated_at", "data"])
        if "coreCase" in paid_patch:
            # Recién con el pago confirmado: si la transacción hace rollback,
            # nadie recibe un aviso de un core que no existe.
            transaction.on_commit(lambda: notify_core_opened(order))

        # Los otros pagos abiertos del pedido ya no deben cobrarse.
        superseded = Payment.objects.select_for_update().filter(
            order=order, status=PaymentStatus.PENDING
        )
        for other in superseded:
            cancel_pending_payment(other, "SUPERSEDED", data={"supersededBy": payment.pk})

        if closed:
            logger.warning(
                "Authorize.net transaction %s paid %s on %s order %s (payment %s); "
                "refund required",
                tid,
                payment.amount,
                order.status,
                order.pk,
                payment.pk,
            )
            record_activity(
                actor=PROVIDER_ACTOR,
                action="PAYMENT_ON_CLOSED_ORDER",
                entity_type="ORDER",
                entity_id=order.pk,
                data={**activity, "paymentId": payment.pk, "orderStatus": order.status},
            )
            return

        record_activity(
            actor=PROVIDER_ACTOR,
            action="PAYMENT_PAID",
            entity_type="ORDER",
            entity_id=order.pk,
            data=activity,
        )


def reconcile_fraud_declined(trans_id) -> None:
    """`fraud.declined`: el filtro de fraude rechazó el cobro; el pago pasa a
    FAILED y el pedido también, salvo que otro cobro ya lo haya pagado."""
    details = _details(trans_id, "fraud declined")
    if details is None:
        return
    payment = _charge_payment(details, "fraud declined")
    if payment is None:
        return

    now = timezone.now()
    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        if payment.status != PaymentStatus.PENDING:
            return
        payment.status = PaymentStatus.FAILED
        payment.updated_at = now
        payment.data = {
            **(payment.data or {}),
            "transactionId": details["id"],
            "failureReason": "FRAUD_DECLINED",
        }
        payment.save(update_fields=["status", "updated_at", "data"])
        if order is not None and order.payment_status not in (
            *CHARGED_PAYMENT_STATUSES,
            OrderPaymentStatus.FAILED,
        ):
            order.payment_status = OrderPaymentStatus.FAILED
            order.updated_at = now
            order.save(update_fields=["payment_status", "updated_at"])


def reconcile_fraud_held(trans_id) -> None:
    """`fraud.held`: el filtro de fraude retuvo el cobro para revisión manual
    en el panel de Authorize.net. El pedido sigue sin pagar hasta
    `fraud.approved`."""
    details = _details(trans_id, "fraud held")
    if details is not None:
        _flag_fraud_hold(details)


def _flag_fraud_hold(details: dict) -> None:
    """Guarda el aviso en `order.data.fraudWarning` y lo registra en la
    bitácora. No cambia el estado del pedido: el staff decide en el panel de
    Authorize.net. Idempotente por el id de la transacción."""
    payment = _charge_payment(details, "fraud hold")
    if payment is None:
        return
    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        if order is None:
            return
        order_data = order.data or {}
        if (order_data.get("fraudWarning") or {}).get("id") == details["id"]:
            return
        logger.warning(
            "Authorize.net held transaction %s for fraud review on order %s (payment %s)",
            details["id"],
            order.pk,
            payment.pk,
        )
        patch = {
            "id": details["id"],
            "status": details.get("status"),
            "receivedAt": timezone.now().isoformat(),
        }
        order.data = {**order_data, "fraudWarning": patch}
        order.updated_at = timezone.now()
        order.save(update_fields=["data", "updated_at"])
        record_activity(
            actor=PROVIDER_ACTOR,
            action="FRAUD_WARNING_RECEIVED",
            entity_type="ORDER",
            entity_id=order.pk,
            data={**patch, "paymentId": payment.pk, "transactionId": details["id"]},
        )


def reconcile_refund(trans_id) -> None:
    """`refund.created`: un reembolso de una transacción liquidada, pedido
    desde el panel o desde el Merchant Interface. Crea o actualiza la fila
    `Refund` (idempotente por `provider_refund_id`)."""
    details = _details(trans_id, "refund")
    if details is None or details.get("type") != "refundTransaction":
        return
    payment = _paid_payment(details.get("refTransId"), "refund")
    if payment is None:
        return
    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        if order is None:
            return
        sync_provider_refund(order, payment, details)


def reconcile_void(trans_id) -> None:
    """`void.created`: se anuló una transacción sin liquidar. Si era un cobro
    nuestro, cuenta como reembolso total."""
    details = _details(trans_id, "void")
    if details is None or details.get("status") != "voided":
        return
    payment = _paid_payment(details.get("id"), "void")
    if payment is None:
        return
    with transaction.atomic():
        order, payment = lock_order_and_payment(payment)
        if order is None:
            return
        sync_provider_void(order, payment)


EVENT_HANDLERS = {
    "net.authorize.payment.authcapture.created": reconcile_charge,
    "net.authorize.payment.fraud.approved": reconcile_charge,
    "net.authorize.payment.fraud.held": reconcile_fraud_held,
    "net.authorize.payment.fraud.declined": reconcile_fraud_declined,
    "net.authorize.payment.refund.created": reconcile_refund,
    "net.authorize.payment.void.created": reconcile_void,
}


def handle_webhook_event(event: dict) -> None:
    """Despacha un evento ya verificado. Lanza `ProviderError` si no se pudo
    releer la transacción, para que Authorize.net reintente."""
    handler = EVENT_HANDLERS.get(event.get("eventType"))
    if handler is None:
        return
    payload = event.get("payload") or {}
    if payload.get("entityName") not in (None, "transaction"):
        return
    handler(payload.get("id"))
