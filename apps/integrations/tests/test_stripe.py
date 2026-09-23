"""La firma del webhook se verifica con el SDK real porque es un HMAC local;
solo se parchean las llamadas de red."""
import hashlib
import hmac
import json
import time

import pytest
import stripe as stripe_sdk

from apps.integrations.exceptions import (
    ProviderError,
    ProviderNotConfigured,
    WebhookSignatureError,
)
from apps.integrations.payments import stripe

SECRET_KEY = "sk_test_fake_not_real"
WEBHOOK_SECRET = "whsec_test_fake_not_real"
SESSION_ARGS = {
    "client_reference_id": "OID1",
    "line_items": [
        {"name": "Injection Pump", "unit_amount": 18999, "quantity": 2},
        {"name": "Shipping", "unit_amount": 1500, "quantity": 1},
    ],
    "success_url": "https://shop.example.com/ok",
    "cancel_url": "https://shop.example.com/cancel",
    "metadata": {"order_id": "OID1", "order_number": "O10001"},
}


def _sign(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    ts = int(time.time())
    signature = hmac.new(
        secret.encode(), f"{ts}.{payload.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    return f"t={ts},v1={signature}"


# --- create_checkout_session ------------------------------------------------


def test_checkout_session_not_configured_never_calls_stripe(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = ""

    def _boom(**kwargs):
        raise AssertionError("Stripe must not be called without a key")

    monkeypatch.setattr("stripe.checkout.Session.create", _boom)

    assert stripe.is_configured() is False
    with pytest.raises(ProviderNotConfigured):
        stripe.create_checkout_session(**SESSION_ARGS)


def test_checkout_session_maps_line_items_and_returns_id_and_url(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = SECRET_KEY
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return {"id": "cs_test_1", "url": "https://checkout.stripe.com/pay/cs_test_1", "x": 1}

    monkeypatch.setattr("stripe.checkout.Session.create", _create)

    result = stripe.create_checkout_session(**SESSION_ARGS, customer_email="pat@example.com")

    assert result == {"id": "cs_test_1", "url": "https://checkout.stripe.com/pay/cs_test_1"}
    assert captured == {
        "api_key": SECRET_KEY,
        "mode": "payment",
        "client_reference_id": "OID1",
        "success_url": "https://shop.example.com/ok",
        "cancel_url": "https://shop.example.com/cancel",
        "metadata": {"order_id": "OID1", "order_number": "O10001"},
        "customer_email": "pat@example.com",
        "line_items": [
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Injection Pump"},
                    "unit_amount": 18999,
                },
                "quantity": 2,
            },
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Shipping"},
                    "unit_amount": 1500,
                },
                "quantity": 1,
            },
        ],
    }


def test_checkout_session_omits_customer_email_when_missing(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = SECRET_KEY
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return {"id": "cs_test_2", "url": "https://checkout.stripe.com/pay/cs_test_2"}

    monkeypatch.setattr("stripe.checkout.Session.create", _create)

    stripe.create_checkout_session(**SESSION_ARGS)

    assert "customer_email" not in captured


def test_checkout_session_stripe_error_maps_to_provider_error(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = SECRET_KEY

    def _raise(**kwargs):
        raise stripe_sdk.APIConnectionError("Stripe is unreachable")

    monkeypatch.setattr("stripe.checkout.Session.create", _raise)

    with pytest.raises(ProviderError, match="Stripe is unreachable"):
        stripe.create_checkout_session(**SESSION_ARGS)


# --- expire_checkout_session ------------------------------------------------


def test_expire_session_not_configured_never_calls_stripe(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = ""

    def _boom(*args, **kwargs):
        raise AssertionError("Stripe must not be called without a key")

    monkeypatch.setattr("stripe.checkout.Session.expire", _boom)

    with pytest.raises(ProviderNotConfigured):
        stripe.expire_checkout_session("cs_open")


def test_expire_session_passes_the_key_per_call(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = SECRET_KEY
    captured = {}

    def _expire(session_id, **kwargs):
        captured.update({"id": session_id, **kwargs})
        return {"id": session_id, "status": "expired", "object": "checkout.session"}

    monkeypatch.setattr("stripe.checkout.Session.expire", _expire)

    assert stripe.expire_checkout_session("cs_open") == {
        "id": "cs_open",
        "status": "expired",
        "alreadyClosed": False,
    }
    assert captured == {"id": "cs_open", "api_key": SECRET_KEY}


@pytest.mark.parametrize("status", ["expired", "complete"])
def test_expire_session_that_is_no_longer_open_is_reported_not_raised(
    settings, monkeypatch, status
):
    # Stripe responde 400 si la sesión ya no está `open`; se relee para
    # distinguir "ya cerrada" (éxito) de un error real.
    settings.STRIPE_SECRET_KEY = SECRET_KEY

    def _expire(session_id, **kwargs):
        raise stripe_sdk.InvalidRequestError(
            'Only Checkout Sessions with a status in ["open"] can be expired.', param=None
        )

    monkeypatch.setattr("stripe.checkout.Session.expire", _expire)
    monkeypatch.setattr(
        "stripe.checkout.Session.retrieve",
        lambda session_id, **kwargs: {"id": session_id, "status": status},
    )

    assert stripe.expire_checkout_session("cs_done") == {
        "id": "cs_done",
        "status": status,
        "alreadyClosed": True,
    }


def test_expire_session_invalid_request_on_an_open_session_is_a_provider_error(
    settings, monkeypatch
):
    settings.STRIPE_SECRET_KEY = SECRET_KEY

    def _expire(session_id, **kwargs):
        raise stripe_sdk.InvalidRequestError("Something else", param=None)

    monkeypatch.setattr("stripe.checkout.Session.expire", _expire)
    monkeypatch.setattr(
        "stripe.checkout.Session.retrieve",
        lambda session_id, **kwargs: {"id": session_id, "status": "open"},
    )

    with pytest.raises(ProviderError, match="Something else"):
        stripe.expire_checkout_session("cs_open")


def test_expire_session_unknown_session_is_a_provider_error(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = SECRET_KEY

    def _raise(session_id, **kwargs):
        raise stripe_sdk.InvalidRequestError("No such checkout.session", param="session")

    monkeypatch.setattr("stripe.checkout.Session.expire", _raise)
    monkeypatch.setattr("stripe.checkout.Session.retrieve", _raise)

    with pytest.raises(ProviderError, match="No such checkout.session"):
        stripe.expire_checkout_session("cs_missing")


def test_expire_session_network_error_maps_to_provider_error(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = SECRET_KEY

    def _raise(session_id, **kwargs):
        raise stripe_sdk.APIConnectionError("Stripe is unreachable")

    monkeypatch.setattr("stripe.checkout.Session.expire", _raise)

    with pytest.raises(ProviderError, match="Stripe is unreachable"):
        stripe.expire_checkout_session("cs_open")


# --- retrieve_payment_method ------------------------------------------------


def test_payment_method_not_configured_raises(settings):
    settings.STRIPE_SECRET_KEY = ""

    with pytest.raises(ProviderNotConfigured):
        stripe.retrieve_payment_method("pi_1")


def test_payment_method_maps_the_card(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = SECRET_KEY
    captured = {}

    def _retrieve(intent_id, **kwargs):
        captured.update({"id": intent_id, **kwargs})
        return {
            "id": "pi_1",
            "payment_method": {
                "id": "pm_1",
                "card": {"brand": "visa", "last4": "4242", "funding": "credit"},
            },
        }

    monkeypatch.setattr("stripe.PaymentIntent.retrieve", _retrieve)

    assert stripe.retrieve_payment_method("pi_1") == {
        "paymentIntent": "pi_1",
        "paymentMethodId": "pm_1",
        "brand": "visa",
        "last4": "4242",
        "funding": "credit",
    }
    assert captured == {"id": "pi_1", "expand": ["payment_method"], "api_key": SECRET_KEY}


def test_payment_method_not_expanded_keeps_only_the_id(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = SECRET_KEY
    monkeypatch.setattr(
        "stripe.PaymentIntent.retrieve",
        lambda intent_id, **kwargs: {"id": "pi_2", "payment_method": "pm_2"},
    )

    assert stripe.retrieve_payment_method("pi_2") == {
        "paymentIntent": "pi_2",
        "paymentMethodId": "pm_2",
    }


def test_payment_method_stripe_error_maps_to_provider_error(settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = SECRET_KEY

    def _raise(intent_id, **kwargs):
        raise stripe_sdk.InvalidRequestError("No such payment_intent", param="id")

    monkeypatch.setattr("stripe.PaymentIntent.retrieve", _raise)

    with pytest.raises(ProviderError):
        stripe.retrieve_payment_method("pi_missing")


# --- construct_webhook_event ------------------------------------------------


def test_webhook_without_secret_raises_not_configured(settings):
    settings.STRIPE_WEBHOOK_SECRET = ""

    with pytest.raises(ProviderNotConfigured):
        stripe.construct_webhook_event(b"{}", "t=1,v1=deadbeef")


def test_webhook_valid_signature_returns_a_plain_dict(settings):
    settings.STRIPE_WEBHOOK_SECRET = WEBHOOK_SECRET
    event = {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {"id": "cs"}}}
    payload = json.dumps(event).encode()

    result = stripe.construct_webhook_event(payload, _sign(payload))

    assert result == event
    assert type(result) is dict


@pytest.mark.parametrize(
    "payload, signature",
    [
        (b'{"id": "evt_1"}', "t=1,v1=" + "0" * 64),
        (b'{"id": "evt_1"}', ""),
        (b"not json", None),
    ],
)
def test_webhook_bad_signature_or_payload_raises(settings, payload, signature):
    settings.STRIPE_WEBHOOK_SECRET = WEBHOOK_SECRET
    header = _sign(payload) if signature is None else signature

    with pytest.raises(WebhookSignatureError):
        stripe.construct_webhook_event(payload, header)
