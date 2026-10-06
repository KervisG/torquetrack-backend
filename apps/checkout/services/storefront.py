"""Checkout del storefront: arma el pedido desde el carrito y abre su pago."""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.cart.models import CartStage, CartStatus
from apps.catalog.services.pricing import (
    STOREFRONT_QUANTITY_ERROR,
    InvalidQuantity,
    PricedLine,
    UnpricedProducts,
    build_totals,
    price_lines,
    serialize_totals,
)
from apps.checkout.models import Order, OrderPaymentStatus, OrderStatus
from apps.checkout.services.payments import cancel_unpaid_order, start_stripe_payment
from apps.common.contact import is_plausible_phone, is_valid_email
from apps.common.errors import error_payload
from apps.common.ids import random_id
from apps.common.numbers import money
from apps.common.us_addresses import (
    normalize_state_code,
    shipping_state_error,
    shipping_zip_error,
)
from apps.customers.services import customer_for_user, resolve_guest_customer
from apps.integrations.exceptions import ProviderError
from apps.numbering.services import next_document_number
from apps.vin.services import VIN_FORMAT_ERROR, VIN_PATTERN

logger = logging.getLogger(__name__)

# El detalle de Stripe va al log: puede nombrar la cuenta o la configuración.
PAYMENT_START_FAILED = "Payment could not be started. Please try again."


def next_order_number() -> str:
    return next_document_number("order", "O")


def _order_item(line: PricedLine) -> dict:
    product_data = line.product
    return {
        "id": product_data.get("id"),
        "title": (
            product_data.get("title") or product_data.get("partNumber") or product_data.get("id")
        ),
        "partNumber": (
            product_data.get("partNumber")
            or product_data.get("oemPart")
            or product_data.get("aftermarketPart")
            or ""
        ),
        "qty": line.quantity,
        "price": money(line.unit_price),
        "coreCharge": money(line.core_charge),
    }


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
        "stage": CartStage.CHECKOUT,
        "status": CartStatus.CHECKOUT,
        "orderId": order.pk,
        "orderNumber": order.number,
        "customer": customer,
    }
    cart.updated_at = timezone.now()
    cart.save(update_fields=["data", "updated_at"])


# Mismas reglas y mensajes que `src/lib/validators/checkout-customer.ts`.
INVALID_EMAIL = "Valid email required"
INVALID_PHONE = "Phone must have 10 to 15 digits"
ADDRESS1_REQUIRED = "Street address required"
CITY_REQUIRED = "City required"


def _clean_contact(customer: dict) -> tuple[str, str] | None:
    """Valida el contacto del pedido y recorta en el lugar el correo, la calle
    y la ciudad. Devuelve `(mensaje, campo)` del primer error, o `None`. El
    teléfono es opcional y se guarda con el formato que tipeó el cliente."""
    if not is_valid_email(customer.get("email")):
        return INVALID_EMAIL, "email"
    phone = customer.get("phone")
    phone = phone.strip() if isinstance(phone, str) else phone
    if phone and not is_plausible_phone(phone):
        return INVALID_PHONE, "phone"
    for key, message in (("address1", ADDRESS1_REQUIRED), ("city", CITY_REQUIRED)):
        value = customer.get(key)
        if not isinstance(value, str) or not value.strip():
            return message, key
    for key in ("email", "address1", "city"):
        customer[key] = customer[key].strip()
    return None


def create_storefront_checkout(user, body: dict, cart_id=None) -> tuple[dict, int]:
    """Nunca confía en montos del cliente: reprecia desde la base, vuelve a
    chequear el fitment, cobra solo la tarifa de envío que el servidor cotizó
    para ese ZIP y omite el impuesto únicamente con un perfil VERIFIED
    vinculado a la sesión.

    El pedido se crea antes de Stripe porque la sesión necesita su id y su
    número. Si Stripe falla, el pedido queda `CANCELLED` y el carrito no pasa a
    `CHECKOUT`: el carrito solo se vincula cuando la sesión existe.

    `cart_id` es el carrito de la cuenta o, sin ella, el de la sesión; el
    `cartId` del body se ignora para que nadie pueda marcar como vendido el
    carrito de otro.
    """
    from apps.fitment.services import applications_by_product, check_product_fitment
    from apps.shipping.services import verify_shipping_selection
    from apps.tax.services import calculate_sales_tax, is_tax_exempt

    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return {"error": "Cart is empty"}, 400
    if not all(isinstance(raw_item, dict) for raw_item in raw_items):
        return {"error": "Each cart item must be an object with an id and qty"}, 400
    raw_customer = _object_or_empty(body.get("customer"))
    vehicle = _object_or_empty(body.get("vehicle"))
    if raw_customer is None or vehicle is None:
        return {"error": "Customer and vehicle must be objects"}, 400
    # El VIN es opcional: sin él se compra igual, pero uno tipeado tiene que
    # ser un VIN válido para no guardar en el pedido un vehículo inventado.
    vin = str(vehicle.get("vin") or "").strip().upper()
    vehicle = {key: value for key, value in vehicle.items() if key != "vin"}
    if vin:
        if not VIN_PATTERN.match(vin):
            return error_payload(VIN_FORMAT_ERROR, "vin"), 400
        vehicle["vin"] = vin

    # El precio sale siempre del catálogo; un precio ausente o no positivo
    # es un error de carga y se rechaza antes de crear el pedido para no
    # cobrar la pieza gratis.
    try:
        priced = price_lines(raw_items)
    except InvalidQuantity:
        return {"error": STOREFRONT_QUANTITY_ERROR}, 400
    except UnpricedProducts as exc:
        detail = ", ".join(
            item["partNumber"] or item["title"] for item in map(_order_item, exc.lines)
        )
        return {
            "error": f"These items have no valid price and cannot be purchased online: {detail}"
        }, 409
    if not priced.lines:
        return {"error": "No valid products in cart"}, 400
    pairs = [(_order_item(line), line.product) for line in priced.lines]

    # Con filas de `ProductFitment` manda la relación; sin ellas, el texto.
    # El id es el del item (la pk que encontró `price_lines`): `data` puede no
    # traer `id`.
    line_ids = [str(line.item.get("productId") or line.item.get("id")) for line in priced.lines]
    fitments = applications_by_product(line_ids)
    incompatible = [
        (item, check_product_fitment(data, vehicle, fitments.get(product_id)))
        for (item, data), product_id in zip(pairs, line_ids, strict=True)
    ]
    incompatible = [(item, check) for item, check in incompatible if not check["compatible"]]
    if incompatible:
        detail = "; ".join(
            f"{item['partNumber'] or item['title']}: {', '.join(check['reasons'])}"
            for item, check in incompatible
        )
        return error_payload(f"VIN fitment check failed: {detail}", "vehicle"), 409

    # Con perfil vinculado el pedido es de la cuenta y su email manda; el
    # perfil nunca se reescribe con el body.
    profile = customer_for_user(user)
    customer = dict(raw_customer)
    if profile is not None:
        customer["email"] = profile.email or user.email

    if contact_error := _clean_contact(customer):
        return error_payload(*contact_error), 400

    # El nexo depende del estado: sin uno válido, un envío a Florida pagaría 0
    # de impuesto. El perfil no lo completa; la dirección del pedido es la del body.
    state_error = shipping_state_error(customer.get("state"))
    if state_error:
        return error_payload(state_error, "state"), 400
    customer["state"] = normalize_state_code(customer["state"])
    zip_code = customer.get("zip")
    zip_code = zip_code.strip() if isinstance(zip_code, str) else zip_code
    zip_error = shipping_zip_error(zip_code, customer["state"])
    if zip_error:
        return error_payload(zip_error, "zip"), 400
    customer["zip"] = zip_code

    selection = body.get("shipping")
    if not (
        isinstance(selection, dict) and selection.get("shipmentId") and selection.get("rateId")
    ):
        return error_payload("Select a shipping method before payment.", "shipping"), 400
    shipping_rate = verify_shipping_selection(selection, customer.get("zip"), items=raw_items)
    if shipping_rate is None:
        return error_payload(
            "Shipping rate could not be verified. Get shipping rates again.", "shipping"
        ), 409
    shipping = shipping_rate["rate"]

    # La exención sale solo del perfil de la sesión: un email tipeado por un
    # invitado no prueba que el comprador sea ese cliente exento.
    if is_tax_exempt(profile):
        tax_result = {"tax": 0, "rate": 0, "source": "Tax exempt"}
    else:
        tax_result = calculate_sales_tax(
            subtotal=priced.subtotal,
            core_charge=priced.core,
            shipping=shipping,
            state=customer.get("state"),
            zip_code=customer.get("zip"),
            city=customer.get("city"),
            address1=customer.get("address1"),
        )
    totals = build_totals(priced.subtotal, priced.core, shipping, tax_result["tax"])

    with transaction.atomic():
        if profile is not None:
            customer_id = profile.pk
        else:
            customer_id = resolve_guest_customer(customer)
        order = Order.objects.create(
            id=random_id("OID"),
            number=next_order_number(),
            customer_id=customer_id,
            status=OrderStatus.PENDING_PAYMENT,
            payment_status=OrderPaymentStatus.UNPAID,
            data={
                "customer": customer,
                "vehicle": vehicle,
                "items": [item for item, _ in pairs],
                "shipping": shipping_rate,
                "cartId": cart_id,
                "taxSource": tax_result["source"],
                "totals": serialize_totals(totals),
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
            "tax": money(totals["tax"]),
        },
        200,
    )
