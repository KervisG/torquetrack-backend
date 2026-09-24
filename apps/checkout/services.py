"""Checkout: pedidos del storefront, pagos de Stripe y conciliación del webhook."""
from __future__ import annotations

import logging
from urllib.parse import quote

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity
from apps.checkout.models import Order, Payment
from apps.common.ids import random_id
from apps.common.links import app_url
from apps.common.numbers import money, money_decimal, to_number
from apps.customers.services import customer_for_user, resolve_guest_customer
from apps.integrations.exceptions import ProviderError
from apps.integrations.payments import stripe as stripe_payments
from apps.numbering.services import next_document_number

logger = logging.getLogger(__name__)

# El detalle de Stripe va al log: puede nombrar la cuenta o la configuración.
PAYMENT_START_FAILED = "Payment could not be started. Please try again."


def next_order_number() -> str:
    return next_document_number("order", "O")


# --- Stripe ---------------------------------------------------------------


def _line(name: str, unit_price: float, qty: int) -> dict:
    return {"name": name, "unit_amount": int(money_decimal(unit_price) * 100), "quantity": qty}


def _create_checkout_session(order: dict) -> dict:
    """Devuelve `{"id", "url"}`; lanza `ProviderError` o `ProviderNotConfigured`."""
    items = order.get("items") or []
    totals = order.get("totals") or {}
    line_items = []
    for item in items:
        qty = max(1, int(to_number(item.get("qty") or item.get("quantity"), 1)))
        price = money(item.get("price") if item.get("price") is not None else item.get("unitPrice"))
        core = money(item.get("coreCharge"))
        title = item.get("title") or item.get("partNumber") or "Diesel Part"
        line_items.append(_line(title, price, qty))
        if core > 0:
            line_items.append(_line(f"Core charge — {title}", core, qty))

    for name, value in (
        ("Shipping", money(totals.get("shipping"))),
        ("Sales Tax", money(totals.get("tax"))),
    ):
        if value > 0:
            line_items.append(_line(name, value, 1))

    order_id = str(order["id"])
    return stripe_payments.create_checkout_session(
        client_reference_id=order_id,
        line_items=line_items,
        success_url=app_url(
            f"/checkout-success.html?session_id={{CHECKOUT_SESSION_ID}}&order_id={quote(order_id)}"
        ),
        cancel_url=app_url("/checkout.html?canceled=1"),
        metadata={"order_id": order_id, "order_number": order["number"]},
        customer_email=(order.get("customer") or {}).get("email") or None,
    )


def start_stripe_payment(order: Order, *, data: dict | None = None) -> tuple[Payment, dict]:
    """Única forma de cobrar con Stripe, así el monto, su redondeo y el
    `provider_id` que busca el webhook (el id de la sesión) salen de un solo
    lugar. Si Stripe falla lanza `ProviderError` sin dejar ningún `Payment`.
    """
    order_data = order.data or {}
    # El id y el número van al final: un `id` guardado en el jsonb no puede
    # desviar la sesión hacia otro pedido.
    session = _create_checkout_session({**order_data, "id": order.pk, "number": order.number})
    with transaction.atomic():
        payment = Payment.objects.create(
            id=random_id("PAY"),
            order=order,
            provider="stripe",
            provider_id=session["id"],
            status="PENDING",
            amount=money_decimal((order_data.get("totals") or {}).get("total")),
            data={"sessionId": session["id"], **(data or {})},
        )
        # Un pedido tiene una sola sesión cobrable: la anterior (otro link,
        # otro intento de checkout) se expira solo cuando la nueva ya existe.
        previous = (
            Payment.objects.select_for_update()
            .filter(order=order, provider="stripe", status="PENDING")
            .exclude(pk=payment.pk)
        )
        for other in previous:
            cancel_pending_payment(other, "REPLACED", data={"replacedBy": session["id"]})
    return payment, session


def cancel_pending_payment(payment: Payment, reason: str, *, data: dict | None = None) -> None:
    """Única forma de cancelar un pago PENDING, porque además expira su
    Checkout Session para que el cliente ya no pueda pagarla.

    La expiración corre en `on_commit`: si la transacción hace rollback, la
    sesión sigue viva igual que el pago. Un error de Stripe solo se registra;
    en el peor caso el cliente paga una sesión cancelada y el webhook la marca
    para reembolso (`DUPLICATE_PAYMENT_RECEIVED`).
    """
    if payment.status != "PENDING":
        return
    payment.status = "CANCELLED"
    payment.updated_at = timezone.now()
    payment.data = {**(payment.data or {}), "cancelReason": reason, **(data or {})}
    payment.save(update_fields=["status", "updated_at", "data"])

    if payment.provider == "stripe" and payment.provider_id:
        session_id, payment_id = payment.provider_id, payment.pk
        transaction.on_commit(lambda: _expire_stripe_session(session_id, payment_id))


def _expire_stripe_session(session_id: str, payment_id: str) -> None:
    try:
        result = stripe_payments.expire_checkout_session(session_id)
    except ProviderError as exc:
        logger.warning(
            "Could not expire Stripe session %s of cancelled payment %s: %s",
            session_id,
            payment_id,
            exc,
        )
        return
    if result.get("status") == "complete":
        # Se pagó antes de poder expirarla; el webhook la concilia y, si el
        # pedido ya estaba pagado, la marca para reembolso.
        logger.warning(
            "Stripe session %s of cancelled payment %s was already complete",
            session_id,
            payment_id,
        )


def cancel_pending_payments(order: Order, reason: str) -> None:
    with transaction.atomic():
        for payment in Payment.objects.select_for_update().filter(order=order, status="PENDING"):
            cancel_pending_payment(payment, reason)


def cancel_unpaid_order(order: Order, reason: str) -> None:
    """El número queda emitido en el pedido cancelado: la serie no se reutiliza ni se salta."""
    with transaction.atomic():
        order.status = "CANCELLED"
        order.data = {**(order.data or {}), "cancelReason": reason}
        order.updated_at = timezone.now()
        order.save(update_fields=["status", "data", "updated_at"])
        cancel_pending_payments(order, reason)


def get_stripe_payment_method(payment_intent_id) -> dict | None:
    """Dato decorativo: sin key, sin PaymentIntent o con Stripe caído devuelve
    `None` y el webhook concilia igual."""
    if not payment_intent_id:
        return None
    try:
        return stripe_payments.retrieve_payment_method(payment_intent_id)
    except ProviderError:
        return None


# --- Checkout del storefront -------------------------------------------------


def _cart_lines(raw_items: list[dict]) -> tuple[list[tuple[dict, dict]], float, float]:
    """Líneas repreciadas desde la base: `[(item, product_data)]`, subtotal y
    core. Los productos inexistentes o inactivos se descartan."""
    from apps.catalog.models import Product

    ids = [str(raw_item.get("id")) for raw_item in raw_items]
    products_by_id = {
        product.id: (product.data or {})
        for product in Product.objects.filter(id__in=ids, active=True)
    }

    pairs = []
    subtotal = 0.0
    core_total = 0.0
    for raw_item in raw_items:
        product_data = products_by_id.get(str(raw_item.get("id")))
        if not product_data:
            continue
        qty = max(1, min(99, int(to_number(raw_item.get("qty"), 1))))
        price = money(product_data.get("price"))
        core = money(product_data.get("coreCharge"))
        subtotal += price * qty
        core_total += core * qty
        title = (
            product_data.get("title") or product_data.get("partNumber") or product_data.get("id")
        )
        item = {
            "id": product_data.get("id"),
            "title": title,
            "partNumber": (
                product_data.get("partNumber")
                or product_data.get("oemPart")
                or product_data.get("aftermarketPart")
                or ""
            ),
            "qty": qty,
            "price": price,
            "coreCharge": core,
        }
        pairs.append((item, product_data))
    return pairs, subtotal, core_total


def _object_or_empty(value) -> dict | None:
    """`{}` para un campo ausente, el dict si es un objeto y `None` si el
    body mandó otro tipo."""
    if value is None:
        return {}
    return value if isinstance(value, dict) else None


def _link_cart_to_order(cart_id, order: Order, customer: dict) -> None:
    from apps.cart.models import Cart

    cart = Cart.objects.filter(pk=cart_id).first()
    if cart is None:
        return
    cart.data = {
        **(cart.data or {}),
        "stage": "CHECKOUT",
        "status": "CHECKOUT",
        "orderId": order.pk,
        "orderNumber": order.number,
        "customer": customer,
    }
    cart.updated_at = timezone.now()
    cart.save(update_fields=["data", "updated_at"])


def create_storefront_checkout(user, body: dict, cart_id=None) -> tuple[dict, int]:
    """Nunca confía en montos del cliente: reprecia desde la base, vuelve a
    chequear el fitment, cobra solo la tarifa de envío que el servidor cotizó
    para ese ZIP y omite el impuesto únicamente con un perfil VERIFIED
    vinculado a la sesión.

    El pedido se crea antes de Stripe porque la sesión necesita su id y su
    número. Si Stripe falla, el pedido queda `CANCELLED` y el carrito no pasa a
    `CHECKOUT`: el carrito solo se vincula cuando la sesión existe.

    `cart_id` es el carrito de la sesión; el `cartId` del body se ignora para
    que nadie pueda marcar como vendido el carrito de otro.
    """
    from apps.fitment.services import check_product_fitment
    from apps.shipping.services import verify_shipping_selection
    from apps.tax.services import calculate_sales_tax

    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return {"error": "Cart is empty"}, 400
    if not all(isinstance(raw_item, dict) for raw_item in raw_items):
        return {"error": "Each cart item must be an object with an id and qty"}, 400
    raw_customer = _object_or_empty(body.get("customer"))
    vehicle = _object_or_empty(body.get("vehicle"))
    if raw_customer is None or vehicle is None:
        return {"error": "Customer and vehicle must be objects"}, 400

    pairs, subtotal, core_total = _cart_lines(raw_items)
    if not pairs:
        return {"error": "No valid products in cart"}, 400

    incompatible = [(item, check_product_fitment(data, vehicle)) for item, data in pairs]
    incompatible = [(item, check) for item, check in incompatible if not check["compatible"]]
    if incompatible:
        detail = "; ".join(
            f"{item['partNumber'] or item['title']}: {', '.join(check['reasons'])}"
            for item, check in incompatible
        )
        return {"error": f"VIN fitment check failed: {detail}"}, 409

    # Con perfil vinculado el pedido es de la cuenta y su email manda; el
    # perfil nunca se reescribe con el body.
    profile = customer_for_user(user)
    customer = dict(raw_customer)
    if profile is not None:
        customer["email"] = profile.email or user.email

    selection = body.get("shipping")
    if not (
        isinstance(selection, dict) and selection.get("shipmentId") and selection.get("rateId")
    ):
        return {"error": "Select a shipping method before payment."}, 400
    shipping_rate = verify_shipping_selection(selection, customer.get("zip"), items=raw_items)
    if shipping_rate is None:
        return {"error": "Shipping rate could not be verified. Get shipping rates again."}, 409
    shipping = shipping_rate["rate"]

    # La exención sale solo del perfil de la sesión: un email tipeado por un
    # invitado no prueba que el comprador sea ese cliente exento.
    if profile is not None and profile.tax_status == "VERIFIED":
        tax_result = {"tax": 0, "rate": 0, "source": "Tax exempt"}
    else:
        tax_result = calculate_sales_tax(
            subtotal=subtotal,
            core_charge=core_total,
            shipping=shipping,
            state=customer.get("state"),
            zip_code=customer.get("zip"),
            city=customer.get("city"),
            address1=customer.get("address1"),
        )
    tax = money(tax_result["tax"])

    with transaction.atomic():
        if profile is not None:
            customer_id = profile.pk
        else:
            customer_id = resolve_guest_customer(customer)
        order = Order.objects.create(
            id=random_id("OID"),
            number=next_order_number(),
            customer_id=customer_id,
            status="PENDING_PAYMENT",
            payment_status="UNPAID",
            data={
                "customer": customer,
                "vehicle": vehicle,
                "items": [item for item, _ in pairs],
                "shipping": shipping_rate,
                "cartId": cart_id,
                "taxSource": tax_result["source"],
                "totals": {
                    "subtotal": money(subtotal),
                    "core": money(core_total),
                    "shipping": shipping,
                    "tax": tax,
                    "total": money(subtotal + core_total + shipping + tax),
                },
            },
        )

    try:
        _, session = start_stripe_payment(order, data={"source": "STOREFRONT_CHECKOUT"})
    except ProviderError as exc:
        logger.warning("Stripe checkout for order %s failed: %s", order.pk, exc)
        cancel_unpaid_order(order, "PAYMENT_SETUP_FAILED")
        return {"error": PAYMENT_START_FAILED}, 502

    if cart_id:
        _link_cart_to_order(cart_id, order, customer)

    return (
        {
            "ok": True,
            "url": session["url"],
            "orderId": order.pk,
            "orderNumber": order.number,
            "tax": tax,
        },
        200,
    )


# --- Webhook de Stripe ---------------------------------------------------------


def _session_payment(session_obj: dict) -> Payment | None:
    """`Payment` de la Checkout Session del evento, o `None` si la sesión no
    es nuestra o no coincide con el pedido de su metadata."""
    session_id = session_obj.get("id")
    metadata = session_obj.get("metadata") or {}
    order_id = metadata.get("order_id") or session_obj.get("client_reference_id")
    payment = (
        Payment.objects.filter(provider="stripe", provider_id=session_id).first()
        if session_id
        else None
    )
    if payment is None or payment.order_id is None or (order_id and payment.order_id != order_id):
        # Se responde 200 igual: reintentar no va a hacer aparecer el pago.
        logger.warning(
            "Stripe session %s for order %s does not match any payment", session_id, order_id
        )
        return None
    return payment


def _locked_order_and_payment(payment: Payment) -> tuple[Order | None, Payment]:
    """Bloquea primero el pedido y después el pago, siempre en ese orden, y
    relee el pago ya bloqueado para ver lo que otro evento acaba de
    confirmar."""
    order = Order.objects.select_for_update().filter(pk=payment.order_id).first()
    return order, Payment.objects.select_for_update().get(pk=payment.pk)


def reconcile_paid_session(session_obj: dict) -> None:
    """`checkout.session.completed` / `async_payment_succeeded`.

    Marca PAID el pago de ESA sesión y el pedido, y cancela las demás
    sesiones pendientes del pedido. Es idempotente: un reenvío del mismo
    evento, o dos eventos de éxito concurrentes, registran una sola vez. Si
    el pedido ya estaba pagado por otra sesión, el cobro igual existe en
    Stripe: el pago queda PAID y la bitácora lo marca para reembolso.
    """
    payment = _session_payment(session_obj)
    if payment is None or payment.status == "PAID":
        return

    # Fuera del bloqueo: es una llamada de red y es solo decorativa.
    method = get_stripe_payment_method(session_obj.get("payment_intent")) or {}
    session_id = session_obj.get("id")
    now = timezone.now()

    with transaction.atomic():
        order, payment = _locked_order_and_payment(payment)
        if order is None or payment.status == "PAID":
            return

        customer_details = session_obj.get("customer_details") or {}
        payment.status = "PAID"
        payment.updated_at = now
        payment.data = {
            **(payment.data or {}),
            "payment_intent": session_obj.get("payment_intent"),
            "payment_status": session_obj.get("payment_status"),
            "customer_email": customer_details.get("email") or session_obj.get("customer_email"),
            "brand": method.get("brand"),
            "last4": method.get("last4"),
            "funding": method.get("funding"),
        }
        payment.save(update_fields=["status", "updated_at", "data"])

        activity = {
            "sessionId": session_id,
            "paymentIntent": session_obj.get("payment_intent"),
            "amountTotal": session_obj.get("amount_total"),
            "brand": method.get("brand"),
            "last4": method.get("last4"),
        }
        if order.payment_status == "PAID":
            record_activity(
                actor="stripe",
                action="DUPLICATE_PAYMENT_RECEIVED",
                entity_type="ORDER",
                entity_id=order.pk,
                data={**activity, "paymentId": payment.pk},
            )
            return

        order_data = order.data or {}
        paid_patch = {
            "payment": {
                "provider": "stripe",
                "brand": method.get("brand"),
                "last4": method.get("last4"),
                "paymentIntent": session_obj.get("payment_intent"),
                "paidAt": now.isoformat(),
            }
        }
        core_amount = money((order_data.get("totals") or {}).get("core"))
        if core_amount > 0 and not order_data.get("coreCase"):
            paid_patch["coreCase"] = {
                "status": "AWAITING CORE",
                "amount": core_amount,
                "createdAt": now.isoformat(),
                "createdBy": "stripe",
            }
        order.status = "OPEN"
        order.payment_status = "PAID"
        order.updated_at = now
        order.data = {**order_data, **paid_patch}
        order.save(update_fields=["status", "payment_status", "updated_at", "data"])

        # Las otras sesiones abiertas del pedido ya no deben cobrarse.
        superseded = Payment.objects.select_for_update().filter(
            order=order, provider="stripe", status="PENDING"
        )
        for other in superseded:
            cancel_pending_payment(other, "SUPERSEDED", data={"supersededBy": session_id})

        record_activity(
            actor="stripe",
            action="PAYMENT_PAID",
            entity_type="ORDER",
            entity_id=order.pk,
            data=activity,
        )


def reconcile_failed_session(session_obj: dict) -> None:
    """`checkout.session.async_payment_failed`: falla el pago de esa sesión;
    el pedido pasa a FAILED salvo que otra sesión ya lo haya pagado."""
    payment = _session_payment(session_obj)
    if payment is None:
        return

    now = timezone.now()
    with transaction.atomic():
        order, payment = _locked_order_and_payment(payment)
        if payment.status != "PENDING":
            return
        payment.status = "FAILED"
        payment.updated_at = now
        payment.save(update_fields=["status", "updated_at"])
        if order is not None and order.payment_status not in ("PAID", "FAILED"):
            order.payment_status = "FAILED"
            order.updated_at = now
            order.save(update_fields=["payment_status", "updated_at"])
