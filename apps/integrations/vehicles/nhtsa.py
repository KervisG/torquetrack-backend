"""API pública sin clave, así que no hay `ProviderNotConfigured`. Un HTTP de
error es `ProviderUnavailable` y un fallo de red o de JSON es `ProviderError`,
porque `apps.vin` responde un mensaje distinto para cada caso."""
from __future__ import annotations

from urllib.parse import quote

import requests

from apps.integrations.exceptions import ProviderError, ProviderUnavailable

NHTSA_DECODE_URL = (
    "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/{vin}?format=json"
)


def decode_vin(vin: str) -> dict | None:
    """Primer resultado de vPIC, o `None` si no hay resultados."""
    try:
        response = requests.get(NHTSA_DECODE_URL.format(vin=quote(vin)), timeout=10)
    except requests.RequestException as exc:
        raise ProviderError("NHTSA request failed") from exc

    if not response.ok:
        raise ProviderUnavailable(f"NHTSA responded {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError("NHTSA returned invalid JSON") from exc

    results = (payload or {}).get("Results") or []
    if not results:
        return None
    result = results[0]
    # `ErrorCode` es una lista separada por comas ("1,14"); el 1 indica que el
    # dígito verificador (posición 9) no cuadra, señal típica de un VIN mal tipeado.
    error_codes = {code.strip() for code in str(result.get("ErrorCode") or "").split(",")}
    return {
        "model_year": result.get("ModelYear"),
        "make": result.get("Make"),
        "model": result.get("Model"),
        "displacement_l": result.get("DisplacementL"),
        "engine_model": result.get("EngineModel"),
        "fuel_type": result.get("FuelTypePrimary"),
        "check_digit_valid": "1" not in error_codes,
    }
