"""Cualquier fallo se reporta como `ProviderError`: el respaldo con la tabla
por estado lo decide `apps.tax`."""
from __future__ import annotations

import requests
from django.conf import settings

from apps.integrations.exceptions import ProviderError, ProviderNotConfigured

TAXJAR_TAXES_URL = "https://api.taxjar.com/v2/taxes"


def is_configured() -> bool:
    return bool(settings.TAXJAR_API_KEY)


def calculate_tax(
    *, from_zip, to_state, to_zip, to_city, to_street, amount, shipping
) -> dict:
    """Devuelve `{"amount_to_collect": float, "rate": float}` para un envío
    dentro de Estados Unidos."""
    if not is_configured():
        raise ProviderNotConfigured("TAXJAR_API_KEY is not set")

    try:
        response = requests.post(
            TAXJAR_TAXES_URL,
            headers={
                "Authorization": f"Bearer {settings.TAXJAR_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from_country": "US",
                "from_zip": from_zip,
                "to_country": "US",
                "to_state": to_state,
                "to_zip": to_zip,
                "to_city": to_city,
                "to_street": to_street,
                # El dominio calcula en `Decimal`, que `requests` no serializa.
                "amount": float(amount),
                "shipping": float(shipping),
            },
            timeout=10,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError("TaxJar request failed") from exc

    if not response.ok:
        raise ProviderError(f"TaxJar responded {response.status_code}")

    tax_block = (payload or {}).get("tax") or {}
    try:
        return {
            "amount_to_collect": float(tax_block.get("amount_to_collect") or 0),
            "rate": float(tax_block.get("rate") or 0),
        }
    except (TypeError, ValueError) as exc:
        raise ProviderError("TaxJar returned an invalid tax block") from exc
