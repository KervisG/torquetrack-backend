"""Adaptador de Authorize.net: se parchea `requests.post` del adaptador y la
firma del webhook se calcula con un HMAC-SHA512 real. Ningún test llega a la
red."""
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
import requests

from apps.integrations.exceptions import (
    ProviderError,
    ProviderNotConfigured,
    WebhookSignatureError,
)
from apps.integrations.payments import authorize_net
from apps.integrations.tests.support import FakeResponse, RecordingPost

LOGIN_ID = "anet_login_fake"
API_SECRET = "anet_key_fake"
WEBHOOK_SECRET = "ANET_SIGNATURE_FAKE_0123456789ABCDEF"
OK = {"messages": {"resultCode": "Ok", "message": [{"code": "I00001", "text": "Successful."}]}}
TOKEN_ARGS = {
    "invoice_number": "PAY0123456789AB",
    "description": "Order O10001",
    "amount": Decimal("415.98"),
    "line_items": [
        {"id": "TT-100", "name": "Injection Pump", "quantity": 2, "unitPrice": Decimal("189.99")},
    ],
    "tax": Decimal("21.00"),
    "shipping": Decimal("15.00"),
    "customer_email": "buyer@example.com",
    "address": {
        "firstName": "Ellen",
        "lastName": "Johnson",
        "address": "14 Main Street",
        "city": "Pecan Springs",
        "state": "TX",
        "zip": "44628",
    },
    "return_url": "https://shop.example.com/checkout-success?order_id=OID1",
    "cancel_url": "https://shop.example.com/checkout?canceled=1",
}


@pytest.fixture
def configured(settings):
    settings.AUTHORIZE_NET_ACCOUNT_ID = LOGIN_ID
    settings.AUTHORIZE_NET_API_SECRET = API_SECRET
    settings.AUTHORIZE_NET_WEBHOOK_SECRET = WEBHOOK_SECRET
    settings.AUTHORIZE_NET_ENVIRONMENT = "sandbox"
    return settings


def _sign(body: bytes, key: str = WEBHOOK_SECRET) -> str:
    return "sha512=" + hmac.new(key.encode(), body, hashlib.sha512).hexdigest().upper()


# --- configuración ----------------------------------------------------------


def test_not_configured_raises_without_calling_the_provider(settings, monkeypatch):
    settings.AUTHORIZE_NET_ACCOUNT_ID = ""
    settings.AUTHORIZE_NET_API_SECRET = ""

    def _boom(*args, **kwargs):
        raise AssertionError("Authorize.net must not be called without credentials")

    monkeypatch.setattr("apps.integrations.payments.authorize_net.requests.post", _boom)

    assert authorize_net.is_configured() is False
    with pytest.raises(ProviderNotConfigured):
        authorize_net.create_hosted_payment_token(**TOKEN_ARGS)
    with pytest.raises(ProviderNotConfigured):
        authorize_net.get_transaction("60001")


@pytest.mark.parametrize(
    ("environment", "api_url", "form_url"),
    [
        (
            "sandbox",
            "https://apitest.authorize.net/xml/v1/request.api",
            "https://test.authorize.net/payment/payment",
        ),
        (
            "production",
            "https://api.authorize.net/xml/v1/request.api",
            "https://accept.authorize.net/payment/payment",
        ),
        (
            "typo",
            "https://apitest.authorize.net/xml/v1/request.api",
            "https://test.authorize.net/payment/payment",
        ),
    ],
)
def test_environment_selects_api_and_form_urls(
    configured, monkeypatch, environment, api_url, form_url
):
    configured.AUTHORIZE_NET_ENVIRONMENT = environment
    post = RecordingPost(FakeResponse({**OK, "token": "tok_1"}, bom=True))
    monkeypatch.setattr("apps.integrations.payments.authorize_net.requests.post", post)

    result = authorize_net.create_hosted_payment_token(**TOKEN_ARGS)

    assert post.calls[0]["url"] == api_url
    assert result == {"token": "tok_1", "formUrl": form_url}


# --- create_hosted_payment_token --------------------------------------------


def test_hosted_token_request_shape(configured, monkeypatch):
    post = RecordingPost(FakeResponse({**OK, "token": "tok_1"}, bom=True))
    monkeypatch.setattr("apps.integrations.payments.authorize_net.requests.post", post)

    authorize_net.create_hosted_payment_token(**TOKEN_ARGS)

    request = post.calls[0]["json"]["getHostedPaymentPageRequest"]
    # El esquema exige `merchantAuthentication` primero.
    assert list(request) == [
        "merchantAuthentication",
        "transactionRequest",
        "hostedPaymentSettings",
    ]
    assert request["merchantAuthentication"] == {
        "name": LOGIN_ID,
        "transactionKey": API_SECRET,
    }
    tx = request["transactionRequest"]
    assert list(tx) == [
        "transactionType",
        "amount",
        "order",
        "lineItems",
        "tax",
        "shipping",
        "customer",
        "billTo",
        "shipTo",
    ]
    assert tx["transactionType"] == "authCaptureTransaction"
    assert tx["amount"] == "415.98"
    assert tx["order"] == {"invoiceNumber": "PAY0123456789AB", "description": "Order O10001"}
    assert tx["lineItems"]["lineItem"] == [
        {
            "itemId": "TT-100",
            "name": "Injection Pump",
            "description": "Injection Pump",
            "quantity": "2",
            "unitPrice": "189.99",
        }
    ]
    assert tx["tax"] == {"amount": "21.00", "name": "Sales Tax"}
    assert tx["shipping"] == {"amount": "15.00", "name": "Shipping"}
    assert tx["customer"] == {"email": "buyer@example.com"}
    assert tx["billTo"]["address"] == "14 Main Street"
    assert tx["billTo"]["country"] == "US"
    assert tx["shipTo"] == tx["billTo"]

    settings_by_name = {
        item["settingName"]: json.loads(item["settingValue"])
        for item in request["hostedPaymentSettings"]["setting"]
    }
    assert settings_by_name["hostedPaymentReturnOptions"]["url"] == TOKEN_ARGS["return_url"]
    assert settings_by_name["hostedPaymentReturnOptions"]["cancelUrl"] == TOKEN_ARGS["cancel_url"]
    assert settings_by_name["hostedPaymentBillingAddressOptions"] == {
        "show": True,
        "required": True,
    }
    assert settings_by_name["hostedPaymentPaymentOptions"]["showBankAccount"] is False


def test_hosted_token_skips_line_items_over_the_schema_limit_and_cuts_long_names(
    configured, monkeypatch
):
    post = RecordingPost(FakeResponse({**OK, "token": "tok_1"}))
    monkeypatch.setattr("apps.integrations.payments.authorize_net.requests.post", post)
    many = [
        {"id": f"P{i}", "name": "X", "quantity": 1, "unitPrice": Decimal("1.00")} for i in range(31)
    ]

    authorize_net.create_hosted_payment_token(**{**TOKEN_ARGS, "line_items": many})
    tx = post.calls[0]["json"]["getHostedPaymentPageRequest"]["transactionRequest"]
    assert "lineItems" not in tx

    long_line = [{"id": "A" * 40, "name": "B" * 40, "quantity": 1, "unitPrice": Decimal("1")}]
    authorize_net.create_hosted_payment_token(**{**TOKEN_ARGS, "line_items": long_line})
    item = post.calls[1]["json"]["getHostedPaymentPageRequest"]["transactionRequest"]["lineItems"][
        "lineItem"
    ][0]
    assert item["itemId"] == "A" * 31
    assert item["name"] == "B" * 31


def test_hosted_token_without_address_omits_bill_and_ship_to(configured, monkeypatch):
    post = RecordingPost(FakeResponse({**OK, "token": "tok_1"}))
    monkeypatch.setattr("apps.integrations.payments.authorize_net.requests.post", post)

    authorize_net.create_hosted_payment_token(
        **{**TOKEN_ARGS, "address": {"firstName": "Ellen"}, "tax": None, "shipping": 0}
    )

    tx = post.calls[0]["json"]["getHostedPaymentPageRequest"]["transactionRequest"]
    assert "billTo" not in tx and "shipTo" not in tx
    assert "tax" not in tx and "shipping" not in tx


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(
            {
                "messages": {
                    "resultCode": "Error",
                    "message": [{"code": "E00007", "text": "User authentication failed."}],
                }
            }
        ),
        FakeResponse({"error": "boom"}, ok=False, status_code=500),
        FakeResponse(invalid_json=True),
        FakeResponse(OK),  # sin token
    ],
)
def test_hosted_token_failures_raise_provider_error(configured, monkeypatch, response):
    monkeypatch.setattr(
        "apps.integrations.payments.authorize_net.requests.post", RecordingPost(response)
    )
    with pytest.raises(ProviderError):
        authorize_net.create_hosted_payment_token(**TOKEN_ARGS)


def test_network_error_raises_provider_error(configured, monkeypatch):
    def _timeout(*args, **kwargs):
        raise requests.Timeout("slow")

    monkeypatch.setattr("apps.integrations.payments.authorize_net.requests.post", _timeout)
    with pytest.raises(ProviderError):
        authorize_net.get_transaction("60001")


def test_error_message_prefers_the_transaction_error(configured, monkeypatch):
    payload = {
        "transactionResponse": {
            "responseCode": "3",
            "errors": [{"errorCode": "54", "errorText": "Not eligible for credit."}],
        },
        "messages": {"resultCode": "Error", "message": [{"code": "E00027", "text": "Failed."}]},
    }
    monkeypatch.setattr(
        "apps.integrations.payments.authorize_net.requests.post",
        RecordingPost(FakeResponse(payload)),
    )
    with pytest.raises(ProviderError, match="54: Not eligible for credit."):
        authorize_net.refund_transaction(
            trans_id="60001", amount=Decimal("10"), last4="1111", invoice_number="PAY1"
        )


# --- get_transaction ----------------------------------------------------------


def test_get_transaction_normalizes_the_details(configured, monkeypatch):
    payload = {
        **OK,
        "transaction": {
            "transId": "60001",
            "transactionType": "authCaptureTransaction",
            "transactionStatus": "capturedPendingSettlement",
            "responseCode": 1,
            "authAmount": 415.98,
            "settleAmount": 415.98,
            "order": {"invoiceNumber": "PAY0123456789AB"},
            "payment": {"creditCard": {"cardNumber": "XXXX1111", "cardType": "Visa"}},
            "customer": {"email": "buyer@example.com"},
        },
    }
    post = RecordingPost(FakeResponse(payload, bom=True))
    monkeypatch.setattr("apps.integrations.payments.authorize_net.requests.post", post)

    result = authorize_net.get_transaction("60001")

    assert post.calls[0]["json"]["getTransactionDetailsRequest"]["transId"] == "60001"
    assert result == {
        "id": "60001",
        "type": "authCaptureTransaction",
        "status": "capturedPendingSettlement",
        "responseCode": 1,
        "amount": Decimal("415.98"),
        "invoiceNumber": "PAY0123456789AB",
        "refTransId": None,
        "cardType": "Visa",
        "last4": "1111",
        "email": "buyer@example.com",
    }


def test_get_transaction_falls_back_to_auth_amount(configured, monkeypatch):
    payload = {**OK, "transaction": {"transId": "60001", "authAmount": "12.5", "settleAmount": 0}}
    monkeypatch.setattr(
        "apps.integrations.payments.authorize_net.requests.post",
        RecordingPost(FakeResponse(payload)),
    )
    assert authorize_net.get_transaction("60001")["amount"] == Decimal("12.50")


# --- void / refund ------------------------------------------------------------


def test_void_transaction(configured, monkeypatch):
    post = RecordingPost(
        FakeResponse({**OK, "transactionResponse": {"responseCode": "1", "transId": "60002"}})
    )
    monkeypatch.setattr("apps.integrations.payments.authorize_net.requests.post", post)

    assert authorize_net.void_transaction("60001") == {"id": "60002", "approved": True}
    tx = post.calls[0]["json"]["createTransactionRequest"]["transactionRequest"]
    assert tx == {"transactionType": "voidTransaction", "refTransId": "60001"}


def test_refund_transaction(configured, monkeypatch):
    post = RecordingPost(
        FakeResponse({**OK, "transactionResponse": {"responseCode": "1", "transId": "60003"}})
    )
    monkeypatch.setattr("apps.integrations.payments.authorize_net.requests.post", post)

    result = authorize_net.refund_transaction(
        trans_id="60001", amount=Decimal("10"), last4="1111", invoice_number="PAY1"
    )

    assert result == {"id": "60003", "approved": True}
    tx = post.calls[0]["json"]["createTransactionRequest"]["transactionRequest"]
    assert list(tx) == ["transactionType", "amount", "payment", "refTransId", "order"]
    assert tx["amount"] == "10.00"
    assert tx["payment"] == {"creditCard": {"cardNumber": "1111", "expirationDate": "XXXX"}}


def test_declined_refund_is_not_approved(configured, monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.payments.authorize_net.requests.post",
        RecordingPost(
            FakeResponse({**OK, "transactionResponse": {"responseCode": "2", "transId": "0"}})
        ),
    )
    result = authorize_net.refund_transaction(
        trans_id="60001", amount=Decimal("10"), last4="1111", invoice_number="PAY1"
    )
    assert result["approved"] is False


# --- verify_webhook -----------------------------------------------------------


def test_webhook_without_signature_key_is_not_configured(settings):
    settings.AUTHORIZE_NET_WEBHOOK_SECRET = ""
    with pytest.raises(ProviderNotConfigured):
        authorize_net.verify_webhook(b"{}", "sha512=00")


def test_webhook_with_valid_signature_returns_the_event(configured):
    body = json.dumps({"eventType": "net.authorize.payment.authcapture.created"}).encode()

    event = authorize_net.verify_webhook(body, _sign(body))
    assert event["eventType"] == "net.authorize.payment.authcapture.created"

    # Mayúsculas o minúsculas en el hex dan igual.
    assert authorize_net.verify_webhook(body, _sign(body).lower())["eventType"]


@pytest.mark.parametrize(
    "header",
    ["", "sha512=", "sha512=" + "0" * 128, "garbage"],
)
def test_webhook_with_bad_signature_is_rejected(configured, header):
    with pytest.raises(WebhookSignatureError):
        authorize_net.verify_webhook(b'{"eventType": "x"}', header)


def test_webhook_signed_with_another_key_is_rejected(configured):
    body = b'{"eventType": "x"}'
    with pytest.raises(WebhookSignatureError):
        authorize_net.verify_webhook(body, _sign(body, key="OTHER"))


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]"])
def test_webhook_with_valid_signature_but_bad_body_is_rejected(configured, body):
    with pytest.raises(WebhookSignatureError):
        authorize_net.verify_webhook(body, _sign(body))
