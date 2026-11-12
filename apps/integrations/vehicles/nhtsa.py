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
        # Datos de ficha técnica: vPIC los trae vacíos según la marca y el año.
        "engine_manufacturer": result.get("EngineManufacturer"),
        "engine_cylinders": result.get("EngineCylinders"),
        "engine_configuration": result.get("EngineConfiguration"),
        "turbo": result.get("Turbo"),
        "drive_type": result.get("DriveType"),
        "transmission_style": result.get("TransmissionStyle"),
        "transmission_speeds": result.get("TransmissionSpeeds"),
        "body_class": result.get("BodyClass"),
        "trim": result.get("Trim"),
        "gvwr": result.get("GVWR"),
        "vehicle_type": result.get("VehicleType"),
        "series": result.get("Series"),
        "manufacturer": result.get("Manufacturer"),
        "plant_city": result.get("PlantCity"),
        "plant_state": result.get("PlantState"),
        "plant_country": result.get("PlantCountry"),
        "engine_hp": result.get("EngineHP"),
        "brake_system": result.get("BrakeSystemType"),
        "cab_type": result.get("BodyCabType"),
        "check_digit_valid": "1" not in error_codes,
        # Todos los campos con dato, tal cual los nombra vPIC, para "More details".
        "raw": {
            key: str(value).strip()
            for key, value in result.items()
            if str(value or "").strip() and str(value).strip() != "Not Applicable"
        },
    }
