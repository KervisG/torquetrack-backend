"""La key se pasa en cada llamada (`api_key=`) en vez de mutar el global
`stripe.api_key`."""
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
    """Cada línea es `{"name", "unit_amount" (centavos), "quantity"}`."""
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


def expire_checkout_session(session_id: str) -> dict:
    """Stripe rechaza con `InvalidRequestError` expirar una sesión que ya no
    está `open`. En ese caso se relee: si ya estaba `expired` o `complete` se
    devuelve `alreadyClosed=True` en vez de fallar, porque el objetivo (que no
    se pueda pagar) ya se cumplió o ya no depende de nosotros.
    """
    api_key = _secret_key()
    try:
        session = stripe.checkout.Session.expire(session_id, api_key=api_key)
    except stripe.InvalidRequestError as exc:
        closed = _closed_session_status(session_id, api_key)
        if closed is None:
            raise ProviderError(str(exc) or "Stripe request failed") from exc
        return {"id": session_id, "status": closed, "alreadyClosed": True}
    except stripe.StripeError as exc:
        raise ProviderError(str(exc) or "Stripe request failed") from exc
    return {"id": session["id"], "status": session["status"], "alreadyClosed": False}


def _closed_session_status(session_id: str, api_key: str) -> str | None:
    """`None` si sigue `open` o no se pudo leer."""
    try:
        session = stripe.checkout.Session.retrieve(session_id, api_key=api_key)
    except stripe.StripeError:
        return None
    status = session.get("status")
    return status if status in ("expired", "complete") else None


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
    """Sin firma válida no se parsea nada."""
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
