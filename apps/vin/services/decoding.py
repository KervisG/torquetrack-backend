"""Decodificación de VIN; el motor prefiere la cilindrada y cae al modelo de motor."""
from __future__ import annotations

import re

from apps.common.errors import error_payload
from apps.integrations.exceptions import ProviderError, ProviderUnavailable
from apps.integrations.vehicles import nhtsa

# El alfabeto de un VIN nunca incluye I, O ni Q.
VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
VIN_FORMAT_ERROR = "VIN must contain 17 valid characters"
VEHICLE_UNIDENTIFIED_ERROR = (
    "We couldn't identify this vehicle from its VIN. "
    "Use Year / Make / Model to find parts that fit."
)
CHECK_DIGIT_WARNING = "check_digit"
# Campos que el fitment necesita; el orden es el que ve el usuario.
REQUIRED_FIELDS = ("year", "make", "model", "engine")


def decode_vehicle(raw_vin: str | None) -> tuple[dict, int]:
    vin = (raw_vin or "").strip().upper()
    if not VIN_PATTERN.match(vin):
        return error_payload(VIN_FORMAT_ERROR, "vin"), 400

    try:
        result = nhtsa.decode_vin(vin)
    except ProviderUnavailable:
        return {"error": "VIN service unavailable"}, 502
    except ProviderError:
        return {"error": "VIN verification failed"}, 502

    if not result:
        return {"error": "Vehicle not found"}, 404

    vehicle = {
        "vin": vin,
        "year": result["model_year"] or "",
        "make": result["make"] or "",
        "model": result["model"] or "",
        "engine": result["displacement_l"] or result["engine_model"] or "",
        "engineModel": result["engine_model"] or "",
        "fuelType": result["fuel_type"] or "",
    }

    # Sin marca ni motor no hay con qué filtrar el fitment: no se guarda.
    if not vehicle["make"] and not vehicle["engine"]:
        return {"error": VEHICLE_UNIDENTIFIED_ERROR}, 404

    # No se completa nada por fuera del VIN: los campos vacíos se informan
    # tal cual para que el cliente le pida al usuario lo que falta.
    missing = [field for field in REQUIRED_FIELDS if not vehicle[field]]
    warnings = [] if result.get("check_digit_valid", True) else [CHECK_DIGIT_WARNING]
    return {"vehicle": vehicle, "missingFields": missing, "warnings": warnings}, 200
