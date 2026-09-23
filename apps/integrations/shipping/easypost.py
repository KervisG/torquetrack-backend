"""Solo mapea tarifas: elegirlas y armar el paquete es regla de `apps.shipping`."""
from __future__ import annotations

import base64

import requests
from django.conf import settings

from apps.integrations.exceptions import ProviderError, ProviderNotConfigured

EASYPOST_SHIPMENTS_URL = "https://api.easypost.com/v2/shipments"
GENERIC_ERROR = "EasyPost rate request failed"


def is_configured() -> bool:
    return bool(settings.EASYPOST_API_KEY)


def _rate(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "carrier": raw.get("carrier"),
        "service": raw.get("service"),
        "rate": float(raw.get("rate") or 0),
        "delivery_days": raw.get("delivery_days"),
        "guaranteed": bool(raw.get("delivery_date_guaranteed")),
    }


def get_rates(*, to_address, from_address, parcel) -> dict:
    """El `ProviderError` lleva el mensaje de EasyPost, que el dominio muestra
    tal cual al cliente."""
    if not is_configured():
        raise ProviderNotConfigured("EASYPOST_API_KEY is not set")

    auth = base64.b64encode(f"{settings.EASYPOST_API_KEY}:".encode()).decode()
    try:
        response = requests.post(
            EASYPOST_SHIPMENTS_URL,
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            json={
                "shipment": {
                    "to_address": to_address,
                    "from_address": from_address,
                    "parcel": parcel,
                }
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise ProviderError(GENERIC_ERROR) from exc

    try:
        body = response.json() or {}
    except ValueError:
        body = {}

    if not response.ok:
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        raise ProviderError(error.get("message") or GENERIC_ERROR)

    return {
        "shipment_id": body.get("id"),
        "rates": [_rate(raw) for raw in body.get("rates") or []],
    }
