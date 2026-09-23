"""Helpers del checkout: numeración de documentos, resolución del cliente,
armado de la Checkout Session de Stripe y consulta del método de pago.

El impuesto se calcula en `apps.tax.services.calculate_sales_tax`. La
llamada a Stripe vive en el adaptador `apps.integrations.payments.stripe`;
aquí queda lo que es del pedido: las líneas (con el cargo de core aparte, el
envío y el impuesto), las URLs de retorno del SPA y la metadata que usa el
webhook para conciliar.
"""
from __future__ import annotations

import secrets
from urllib.parse import quote

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.checkout.models import DocumentSequence
from apps.customers.models import Customer
from apps.integrations.exceptions import ProviderError
from apps.integrations.payments import stripe as stripe_payments


def js_number_or(raw, fallback=0.0):
    """Mirror JS `Number(raw || fallback)`: falsy `raw` (None/0/""/False)
    uses `fallback`; otherwise coerce `raw` to a number."""
    if raw in (None, False, "", 0, 0.0):
        return fallback
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def money(value) -> float:
    """Mirror JS `Math.round((Number(n)||0)*100)/100`."""
    return round(js_number_or(value, 0.0) * 100) / 100


def random_id(prefix: str) -> str:
    """Id con prefijo: `prefix` más 6 bytes aleatorios en hexadecimal
    mayúscula."""
    return prefix + secrets.token_hex(6).upper()


def linked_customer(user) -> Customer | None:
    """Perfil comercial de la cuenta con sesión, o `None` para un invitado.

    Se exige un `User` real: `AnonymousUser.pk` es `None` y filtrar por
    `user_id=None` devolvería un perfil invitado cualquiera.
    """
    from apps.auth.models import User

    if not isinstance(user, User):
        return None
    return Customer.objects.filter(user=user).first()


def resolve_checkout_customer(user, customer: dict) -> tuple[str | None, dict]:
    """`(customer_id, snapshot)` del comprador de un checkout o cotización.

    Con un `Customer` vinculado a la sesión, el documento es de ese perfil y
    el email del snapshot es el de la cuenta: el body no puede desviar el
    pedido hacia otro cliente ni cambiar el correo de Stripe. El perfil
    nunca se reescribe con el body; el snapshot sí guarda la dirección de
    envío que se escribió en el formulario. Sin perfil vinculado (invitado o
    staff sin perfil) se resuelve por email.
    """
    profile = linked_customer(user)
    if profile is not None:
        return profile.pk, {**customer, "email": profile.email or user.email}
    customer_id = resolve_or_create_customer(customer) if customer.get("email") else None
    return customer_id, customer


def resolve_or_create_customer(customer: dict) -> str | None:
    """Resuelve o crea el cliente por email: combina los campos enviados con
    la fila existente (ganan las claves nuevas) o crea una nueva con
    `random_id("C")`."""
    email = customer.get("email")
    if not email:
        return None

    # Solo perfiles invitados: un email tipeado en el checkout no prueba nada,
    # así que nunca debe mezclarse con el perfil de una cuenta registrada.
    existing = Customer.objects.filter(email__iexact=email, user__isnull=True).first()
    if existing:
        existing.data = {**(existing.data or {}), **customer}
        existing.updated_at = timezone.now()
        existing.save(update_fields=["data", "updated_at"])
        return existing.pk

    customer_id = random_id("C")
    now = timezone.now()
    Customer.objects.create(
        id=customer_id,
        email=email,
        data={**customer, "id": customer_id},
        created_at=now,
        updated_at=now,
    )
    return customer_id


# Los números de pedido y cotización arrancan en 10001.
FIRST_DOCUMENT_NUMBER = 10001


def next_document_number(key: str, prefix: str) -> str:
    """Emite el siguiente número de la serie `key` con formato `<prefix><n>`.

    La fila de la serie (`DocumentSequence`) se bloquea con
    `select_for_update()` dentro de `transaction.atomic`, así que dos requests
    concurrentes nunca emiten el mismo número: cada llamada espera a la
    anterior. Si la fila todavía no existe,
    `get_or_create` la crea y, ante una carrera, reintenta la lectura
    bloqueante en lugar de duplicarla.
    """
    with transaction.atomic():
        sequence, created = DocumentSequence.objects.select_for_update().get_or_create(
            key=key, defaults={"last_value": FIRST_DOCUMENT_NUMBER}
        )
        if not created:
            sequence.last_value += 1
            sequence.save(update_fields=["last_value"])
    return f"{prefix}{sequence.last_value}"


def next_order_number() -> str:
    return next_document_number("order", "O")


def _line(name: str, unit_price: float, qty: int) -> dict:
    return {"name": name, "unit_amount": round(unit_price * 100), "quantity": qty}


def create_stripe_checkout_session(order: dict) -> dict:
    """Abre la Checkout Session del pedido y devuelve `{"id", "url"}`.
    Lanza `ProviderError` (o `ProviderNotConfigured`) del adaptador."""
    items = order.get("items") or []
    totals = order.get("totals") or {}
    app_url = settings.APP_URL or "http://localhost:5173"

    line_items = []
    for item in items:
        qty = max(1, int(js_number_or(item.get("qty") or item.get("quantity"), 1)))
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
        success_url=(
            f"{app_url}/checkout-success.html?session_id={{CHECKOUT_SESSION_ID}}"
            f"&order_id={quote(order_id)}"
        ),
        cancel_url=f"{app_url}/checkout.html?canceled=1",
        metadata={"order_id": order_id, "order_number": order["number"]},
        customer_email=(order.get("customer") or {}).get("email") or None,
    )


def get_stripe_payment_method(payment_intent_id) -> dict | None:
    """Datos de la tarjeta para el pedido pagado, o `None`. Es un dato
    decorativo: sin key, sin PaymentIntent o con Stripe caído, el webhook
    concilia igual."""
    if not payment_intent_id:
        return None
    try:
        return stripe_payments.retrieve_payment_method(payment_intent_id)
    except ProviderError:
        return None


