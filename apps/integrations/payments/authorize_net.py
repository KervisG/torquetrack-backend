"""Adaptador de Authorize.net (API JSON + Accept Hosted).

La API JSON de Authorize.net es una traducción de su XSD: el ORDEN de las
claves importa, por eso cada request se arma con dicts en el orden del
esquema. La respuesta llega con BOM y se decodifica con `utf-8-sig`.

El formulario de tarjeta lo muestra Authorize.net: aquí nunca pasan datos de
tarjeta, solo el token del formulario, ids de transacción y los últimos 4.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

from apps.integrations.exceptions import (
    ProviderError,
    ProviderNotConfigured,
    WebhookSignatureError,
)

API_URLS = {
    "sandbox": "https://apitest.authorize.net/xml/v1/request.api",
    "production": "https://api.authorize.net/xml/v1/request.api",
}
HOSTED_FORM_URLS = {
    "sandbox": "https://test.authorize.net/payment/payment",
    "production": "https://accept.authorize.net/payment/payment",
}
# Topes de longitud del XSD: un valor más largo hace fallar todo el request.
MAX_LINE_ITEMS = 30
MAX_ITEM_ID = 31
MAX_ITEM_NAME = 31
MAX_NAME = 50
MAX_ADDRESS = 60
MAX_CITY = 40
MAX_ZIP = 20
MAX_DESCRIPTION = 255
MERCHANT_NAME = "TorqueTrack"
TIMEOUT_SECONDS = 20


def is_configured() -> bool:
    return bool(settings.AUTHORIZE_NET_ACCOUNT_ID and settings.AUTHORIZE_NET_API_SECRET)


def _environment() -> str:
    env = (settings.AUTHORIZE_NET_ENVIRONMENT or "sandbox").strip().lower()
    return env if env in API_URLS else "sandbox"


def hosted_form_url() -> str:
    return HOSTED_FORM_URLS[_environment()]


def _merchant_authentication() -> dict:
    if not is_configured():
        raise ProviderNotConfigured(
            "AUTHORIZE_NET_ACCOUNT_ID or AUTHORIZE_NET_API_SECRET is not set"
        )
    return {
        "name": settings.AUTHORIZE_NET_ACCOUNT_ID,
        "transactionKey": settings.AUTHORIZE_NET_API_SECRET,
    }


def _error_text(payload: dict) -> str:
    """Primer mensaje de error útil: el de la transacción gana al general."""
    tx_errors = ((payload.get("transactionResponse") or {}).get("errors")) or []
    if tx_errors:
        first = tx_errors[0]
        return f"{first.get('errorCode')}: {first.get('errorText')}"
    messages = (payload.get("messages") or {}).get("message") or []
    if messages:
        first = messages[0]
        return f"{first.get('code')}: {first.get('text')}"
    return "Authorize.net request failed"


def _post(request_name: str, body: dict) -> dict:
    """`merchantAuthentication` va primero porque así lo exige el esquema."""
    payload = {request_name: {"merchantAuthentication": _merchant_authentication(), **body}}
    try:
        response = requests.post(
            API_URLS[_environment()],
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
        data = json.loads(response.content.decode("utf-8-sig"))
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError("Authorize.net request failed") from exc
    if not response.ok:
        raise ProviderError(f"Authorize.net responded {response.status_code}")
    if not isinstance(data, dict):
        raise ProviderError("Authorize.net returned an invalid payload")
    if (data.get("messages") or {}).get("resultCode") != "Ok":
        raise ProviderError(_error_text(data))
    return data


def _amount(value) -> str:
    return f"{Decimal(value).quantize(Decimal('0.01'))}"


def _cut(value, limit: int) -> str:
    return (value or "").strip()[:limit] if isinstance(value, str) else ""


def _address(address: dict | None) -> dict | None:
    """`{"firstName", "lastName", "address", "city", "state", "zip"}` en el
    orden de `customerAddressType`. Sin nombre ni calle no se manda."""
    if not address:
        return None
    first, last = _cut(address.get("firstName"), MAX_NAME), _cut(address.get("lastName"), MAX_NAME)
    street = _cut(address.get("address"), MAX_ADDRESS)
    if not (first or last) or not street:
        return None
    result = {
        "firstName": first,
        "lastName": last,
        "address": street,
        "city": _cut(address.get("city"), MAX_CITY),
        "state": _cut(address.get("state"), MAX_CITY),
        "zip": _cut(address.get("zip"), MAX_ZIP),
        "country": "US",
    }
    return {key: value for key, value in result.items() if value}


def _setting(name: str, value: dict) -> dict:
    # `settingValue` es un string con JSON adentro, no un objeto.
    return {"settingName": name, "settingValue": json.dumps(value)}


def create_hosted_payment_token(
    *,
    invoice_number: str,
    description: str,
    amount,
    line_items: list[dict],
    tax=None,
    shipping=None,
    customer_email: str | None = None,
    address: dict | None = None,
    return_url: str,
    cancel_url: str,
) -> dict:
    """Pide el token de Accept Hosted. Devuelve `{"token", "formUrl"}`.

    `invoice_number` es el id del `Payment`: viaja en la transacción y el
    webhook lo usa para conciliar. Cada línea es `{"id", "name", "quantity",
    "unitPrice"}`; con más de 30 líneas (tope del esquema) se cobra el total
    sin detalle. La dirección del pedido precarga facturación y envío para
    que el AVS la compare con la tarjeta; facturación se exige en el form.
    El token vence a los 15 minutos: se pide justo antes de mostrar el form.
    """
    transaction_request: dict = {
        "transactionType": "authCaptureTransaction",
        "amount": _amount(amount),
        "order": {
            "invoiceNumber": invoice_number,
            "description": _cut(description, MAX_DESCRIPTION),
        },
    }
    if 0 < len(line_items) <= MAX_LINE_ITEMS:
        transaction_request["lineItems"] = {
            "lineItem": [
                {
                    "itemId": _cut(line["id"], MAX_ITEM_ID) or "ITEM",
                    "name": _cut(line["name"], MAX_ITEM_NAME) or "Item",
                    "description": _cut(line["name"], MAX_DESCRIPTION),
                    "quantity": str(line["quantity"]),
                    "unitPrice": _amount(line["unitPrice"]),
                }
                for line in line_items
            ]
        }
    if tax:
        transaction_request["tax"] = {"amount": _amount(tax), "name": "Sales Tax"}
    if shipping:
        transaction_request["shipping"] = {"amount": _amount(shipping), "name": "Shipping"}
    if customer_email:
        transaction_request["customer"] = {"email": customer_email}
    bill_to = _address(address)
    if bill_to:
        transaction_request["billTo"] = bill_to
        transaction_request["shipTo"] = {k: v for k, v in bill_to.items()}

    body = {
        "transactionRequest": transaction_request,
        "hostedPaymentSettings": {
            "setting": [
                _setting(
                    "hostedPaymentReturnOptions",
                    {
                        "showReceipt": False,
                        "url": return_url,
                        "urlText": "Continue",
                        "cancelUrl": cancel_url,
                        "cancelUrlText": "Cancel",
                    },
                ),
                _setting("hostedPaymentButtonOptions", {"text": "Pay"}),
                _setting(
                    "hostedPaymentPaymentOptions",
                    {"cardCodeRequired": True, "showCreditCard": True, "showBankAccount": False},
                ),
                _setting("hostedPaymentBillingAddressOptions", {"show": True, "required": True}),
                _setting(
                    "hostedPaymentShippingAddressOptions", {"show": False, "required": False}
                ),
                _setting(
                    "hostedPaymentCustomerOptions", {"showEmail": True, "requiredEmail": False}
                ),
                _setting(
                    "hostedPaymentOrderOptions", {"show": True, "merchantName": MERCHANT_NAME}
                ),
            ]
        },
    }
    data = _post("getHostedPaymentPageRequest", body)
    token = data.get("token")
    if not isinstance(token, str) or not token:
        raise ProviderError("Authorize.net returned no form token")
    return {"token": token, "formUrl": hosted_form_url()}


def _decimal(value) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount.quantize(Decimal("0.01")) if amount.is_finite() else None


def get_transaction(trans_id: str) -> dict:
    """Detalle normalizado de una transacción:

    `{"id", "type", "status", "responseCode", "amount", "invoiceNumber",
    "refTransId", "cardType", "last4", "email"}`. `amount` es el monto
    liquidado si existe, si no el autorizado; `status` es el
    `transactionStatus` crudo (`capturedPendingSettlement`,
    `settledSuccessfully`, `voided`, `declined`, `FDSPendingReview`, ...).
    """
    data = _post("getTransactionDetailsRequest", {"transId": str(trans_id)})
    tx = data.get("transaction") or {}
    card = ((tx.get("payment") or {}).get("creditCard")) or {}
    card_number = card.get("cardNumber") or ""
    settle = _decimal(tx.get("settleAmount"))
    return {
        "id": str(tx.get("transId") or trans_id),
        "type": tx.get("transactionType"),
        "status": tx.get("transactionStatus"),
        "responseCode": tx.get("responseCode"),
        "amount": settle if settle else _decimal(tx.get("authAmount")),
        "invoiceNumber": (tx.get("order") or {}).get("invoiceNumber"),
        "refTransId": tx.get("refTransId") or None,
        "cardType": card.get("cardType"),
        "last4": card_number[-4:] if card_number else None,
        "email": (tx.get("customer") or {}).get("email"),
    }


def _transaction_result(data: dict) -> dict:
    tx = data.get("transactionResponse") or {}
    return {"id": str(tx.get("transId") or ""), "approved": str(tx.get("responseCode")) == "1"}


def void_transaction(trans_id: str) -> dict:
    """Anula una transacción sin liquidar (siempre por el total).
    Devuelve `{"id", "approved"}`."""
    data = _post(
        "createTransactionRequest",
        {"transactionRequest": {"transactionType": "voidTransaction", "refTransId": str(trans_id)}},
    )
    return _transaction_result(data)


def refund_transaction(*, trans_id: str, amount, last4: str, invoice_number: str) -> dict:
    """Reembolsa una transacción ya liquidada. Authorize.net pide los últimos
    4 de la tarjeta y `XXXX` como vencimiento. Devuelve `{"id", "approved"}`."""
    data = _post(
        "createTransactionRequest",
        {
            "transactionRequest": {
                "transactionType": "refundTransaction",
                "amount": _amount(amount),
                "payment": {"creditCard": {"cardNumber": last4, "expirationDate": "XXXX"}},
                "refTransId": str(trans_id),
                "order": {"invoiceNumber": invoice_number},
            }
        },
    )
    return _transaction_result(data)


def verify_webhook(payload: bytes, signature_header: str) -> dict:
    """`X-ANET-Signature: sha512=<HEX>` es el HMAC-SHA512 del body con la
    Signature Key. Sin firma válida no se parsea nada."""
    key = settings.AUTHORIZE_NET_WEBHOOK_SECRET
    if not key:
        raise ProviderNotConfigured("AUTHORIZE_NET_WEBHOOK_SECRET is not set")
    body = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    received = (signature_header or "").strip()
    if received.lower().startswith("sha512="):
        received = received[len("sha512=") :]
    expected = hmac.new(key.encode("utf-8"), body, hashlib.sha512).hexdigest()
    if not received or not hmac.compare_digest(expected.upper(), received.upper()):
        raise WebhookSignatureError("Invalid Authorize.net webhook signature")
    try:
        event = json.loads(body.decode("utf-8-sig"))
    except ValueError as exc:
        raise WebhookSignatureError("Invalid Authorize.net webhook") from exc
    if not isinstance(event, dict):
        raise WebhookSignatureError("Invalid Authorize.net webhook")
    return event
