"""Adaptador de Stripe con el SDK oficial `stripe` de Python.

Expone tres operaciones: crear una Checkout Session, leer el método de pago
de un PaymentIntent y verificar la firma de un webhook. La key se pasa por
llamada (`api_key=`) en lugar de mutar el global `stripe.api_key`.

Qué queda en `apps.checkout`: armar las líneas del pedido (cargos de core,
envío e impuesto), las URLs de retorno del SPA y la metadata; persistir
`Order` y `Payment`; y conciliar el pedido cuando llega el webhook. El link
de pago y el cobro asistido del panel son Checkout Sessions, así que usan
la misma `create_checkout_session`.
"""
from __future__ import annotations

import json

import stripe
from django.conf import settings

from apps.integrations.exceptions import (
    ProviderError,
    ProviderNotConfigured,
    WebhookSignatureError,
)


def is_configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def _secret_key() -> str:
    if not is_configured():
        raise ProviderNotConfigured("STRIPE_SECRET_KEY is not set")
    return settings.STRIPE_SECRET_KEY


def create_checkout_session(
    *,
    client_reference_id,
    line_items,
    success_url,
    cancel_url,
    metadata,
    customer_email=None,
) -> dict:
    """Crea una Checkout Session en modo `payment` y devuelve `{"id", "url"}`.

    Cada línea es `{"name", "unit_amount" (centavos), "quantity"}` y se
    traduce al `price_data` en USD que espera Stripe.
    """
    params = {
        "api_key": _secret_key(),
        "mode": "payment",
        "client_reference_id": client_reference_id,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": metadata,
        "line_items": [
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": line["name"]},
                    "unit_amount": line["unit_amount"],
                },
                "quantity": line["quantity"],
            }
            for line in line_items
        ],
    }
    if customer_email:
        params["customer_email"] = customer_email

    try:
        session = stripe.checkout.Session.create(**params)
    except stripe.StripeError as exc:
        raise ProviderError(str(exc) or "Stripe request failed") from exc
    return {"id": session["id"], "url": session["url"]}


def retrieve_payment_method(payment_intent_id: str) -> dict:
    """Marca, últimos 4 y tipo de fondos de la tarjeta del PaymentIntent."""
    api_key = _secret_key()
    try:
        intent = stripe.PaymentIntent.retrieve(
            payment_intent_id, expand=["payment_method"], api_key=api_key
        )
    except stripe.StripeError as exc:
        raise ProviderError(str(exc) or "Stripe request failed") from exc

    payment_method = intent.get("payment_method")
    if payment_method and hasattr(payment_method, "get"):
        card = payment_method.get("card") or {}
        return {
            "paymentIntent": intent.get("id"),
            "paymentMethodId": payment_method.get("id"),
            "brand": card.get("brand"),
            "last4": card.get("last4"),
            "funding": card.get("funding"),
        }
    return {
        "paymentIntent": intent.get("id"),
        "paymentMethodId": payment_method if isinstance(payment_method, str) else None,
    }


def construct_webhook_event(payload: bytes, signature_header: str) -> dict:
    """Verifica `Stripe-Signature` con el secreto del webhook y devuelve el
    evento como dict plano. Sin firma válida no se parsea nada."""
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret:
        raise ProviderNotConfigured("STRIPE_WEBHOOK_SECRET is not set")

    try:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        stripe.WebhookSignature.verify_header(text, signature_header, secret)
        event = json.loads(text)
    except (stripe.SignatureVerificationError, ValueError) as exc:
        raise WebhookSignatureError("Invalid Stripe webhook") from exc
    if not isinstance(event, dict):
        raise WebhookSignatureError("Invalid Stripe webhook")
    return event
