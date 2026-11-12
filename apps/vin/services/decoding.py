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


_COMPANY_SUFFIX = re.compile(r"\s+(inc|llc|corp|co)\.?$", re.IGNORECASE)
# `title()` deja "Llc"; las siglas legales vuelven a mayúsculas.
_ACRONYMS = re.compile(r"\b(Llc|Usa)\b")
_CONFIGURATIONS = {"in-line": "I", "v-shaped": "V", "flat": "H", "w-shaped": "W"}


def _text(value) -> str:
    return str(value or "").strip()


def _first(value) -> str:
    """vPIC repite el dato en varias formas ("4WD/4-Wheel Drive/4x4"): se
    muestra la primera, la corta."""
    return _text(value).split("/")[0].strip()


def _engine_description(result: dict) -> str:
    """Arma "Cummins 6.7L I6 Turbodiesel" con lo que vPIC haya traído. Sin
    fabricante se usa el modelo de motor ("International Maxxforce 7")."""
    manufacturer = _COMPANY_SUFFIX.sub("", _text(result.get("engine_manufacturer")))
    name = manufacturer or _text(result.get("engine_model"))
    liters = _text(result.get("displacement_l"))
    try:
        liters = f"{float(liters):.1f}L" if liters else ""
    except ValueError:
        liters = ""
    # Un modelo de motor que ya nombra la cilindrada ("6.7L Power Stroke") no la repite.
    if liters and liters.lower() in name.lower():
        liters = ""
    cylinders = _text(result.get("engine_cylinders"))
    configuration = _CONFIGURATIONS.get(_text(result.get("engine_configuration")).lower(), "")
    if configuration and cylinders:
        layout = f"{configuration}{cylinders}"
    else:
        layout = f"{cylinders} cyl" if cylinders else ""
    diesel = "diesel" in _text(result.get("fuel_type")).lower()
    turbo = _text(result.get("turbo")).lower() == "yes"
    fuel = "Turbodiesel" if diesel and turbo else "Diesel" if diesel else "Turbo" if turbo else ""
    return " ".join(part for part in (name, liters, layout, fuel) if part)


def _transmission(result: dict) -> str:
    style = _first(result.get("transmission_style"))
    speeds = _text(result.get("transmission_speeds"))
    if style and speeds:
        return f"{speeds}-Spd {style}"
    return style


def _horsepower(value) -> str:
    try:
        return f"{float(_text(value)):g} hp" if _text(value) else ""
    except ValueError:
        return ""


def _company(value) -> str:
    return _ACRONYMS.sub(lambda match: match.group(0).upper(), _text(value).title())


def _plant(result: dict) -> str:
    """"Springfield, OH, United States": la planta de ensamblaje del VIN."""
    country = _text(result.get("plant_country")).split("(")[0].strip().title()
    parts = (
        _text(result.get("plant_city")).title(),
        _text(result.get("plant_state")).title(),
        country,
    )
    return ", ".join(part for part in parts if part)


def vehicle_details(result: dict) -> dict:
    """Ficha técnica para mostrar (como la de un listado de concesionario).
    El VIN no codifica colores: no se inventan. Un dato ausente queda vacío."""
    return {
        "engine": _engine_description(result),
        "drivetrain": _first(result.get("drive_type")),
        "transmission": _transmission(result),
        "body": _text(result.get("body_class")),
        "trim": _text(result.get("trim")),
        "gvwr": _text(result.get("gvwr")).split("(")[0].strip(),
        "fuel": _text(result.get("fuel_type")),
        "horsepower": _horsepower(result.get("engine_hp")),
        "vehicleType": _text(result.get("vehicle_type")).title(),
        "series": _text(result.get("series")),
        "cab": _first(result.get("cab_type")),
        "brakes": _text(result.get("brake_system")),
        "manufacturer": _company(result.get("manufacturer")),
        "plant": _plant(result),
    }


# Identificadores internos y metadatos de vPIC: no describen el vehículo.
_HIDDEN_SPECS = {
    "VIN",
    "VehicleDescriptor",
    "SuggestedVIN",
    "ErrorCode",
    "ErrorText",
    "AdditionalErrorText",
    "PossibleValues",
    "Note",
}
_SPEC_WORDS = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _spec_label(key: str) -> str:
    """Separa las palabras: DisplacementCC -> Displacement CC, EngineHP_to -> Engine HP to."""
    return _SPEC_WORDS.sub(" ", key).replace("_", " ").strip()


def vehicle_specs(raw: dict) -> list[dict]:
    """Todos los campos con dato que devolvió vPIC, en su orden, con una
    etiqueta legible. Sin ids (`MakeID`) ni metadatos de error."""
    return [
        {"label": _spec_label(key), "value": value}
        for key, value in raw.items()
        if not _hidden_spec(key)
    ]


def _hidden_spec(key: str) -> bool:
    return key in _HIDDEN_SPECS or key.lower().endswith("id") or key.startswith("NCSAMap")


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
        "details": vehicle_details(result),
        "specs": vehicle_specs(result.get("raw") or {}),
    }

    # Sin marca ni motor no hay con qué filtrar el fitment: no se guarda.
    if not vehicle["make"] and not vehicle["engine"]:
        return {"error": VEHICLE_UNIDENTIFIED_ERROR}, 404

    # No se completa nada por fuera del VIN: los campos vacíos se informan
    # tal cual para que el cliente le pida al usuario lo que falta.
    missing = [field for field in REQUIRED_FIELDS if not vehicle[field]]
    warnings = [] if result.get("check_digit_valid", True) else [CHECK_DIGIT_WARNING]
    return {"vehicle": vehicle, "missingFields": missing, "warnings": warnings}, 200
