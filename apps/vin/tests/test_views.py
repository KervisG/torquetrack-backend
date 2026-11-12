"""`GET /api/vin/decode/`. Se parchea el adaptador de NHTSA
(`apps.integrations.vehicles.nhtsa.decode_vin`); un VIN mal formado no lo
llama. La ruta tiene throttle y sus contadores viven en el cache de la base,
así que cada test pide `db` y limpia el cache.
"""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.integrations.exceptions import ProviderError, ProviderUnavailable

VALID_VIN = "1FTSW21P34EB12345"
DECODED = {
    "model_year": "2004",
    "make": "FORD",
    "model": "F-250",
    "displacement_l": "6.0",
    "engine_model": "POWER STROKE",
    "fuel_type": "Diesel",
    "check_digit_valid": True,
}


@pytest.fixture(autouse=True)
def _clear_throttle_history(db):
    cache.clear()
    yield
    cache.clear()


def _nhtsa(monkeypatch, result=None, error=None):
    calls = []

    def _decode(vin):
        calls.append(vin)
        if error is not None:
            raise error
        return result

    monkeypatch.setattr("apps.integrations.vehicles.nhtsa.decode_vin", _decode)
    return calls


def _boom(vin):
    raise AssertionError("NHTSA must not be called for a malformed VIN")


def test_malformed_vin_returns_400(monkeypatch):
    monkeypatch.setattr("apps.integrations.vehicles.nhtsa.decode_vin", _boom)

    response = APIClient().get("/api/vin/decode/", {"vin": "TOO-SHORT"})

    assert response.status_code == 400
    assert response.json()["error"] == "VIN must contain 17 valid characters"


def test_vin_with_excluded_characters_i_o_q_returns_400(monkeypatch):
    monkeypatch.setattr("apps.integrations.vehicles.nhtsa.decode_vin", _boom)

    response = APIClient().get("/api/vin/decode/", {"vin": "IOQ" + "1" * 14})

    assert response.status_code == 400


def test_valid_vin_returns_decoded_vehicle(monkeypatch):
    calls = _nhtsa(monkeypatch, result=DECODED)

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN.lower()})

    assert response.status_code == 200
    assert calls == [VALID_VIN]
    assert response.json() == {
        "vehicle": {
            "vin": VALID_VIN,
            "year": "2004",
            "make": "FORD",
            "model": "F-250",
            "engine": "6.0",
            "engineModel": "POWER STROKE",
            "fuelType": "Diesel",
            "details": {
                "engine": "POWER STROKE 6.0L Diesel",
                "drivetrain": "",
                "transmission": "",
                "body": "",
                "trim": "",
                "gvwr": "",
                "fuel": "Diesel",
                "horsepower": "",
                "vehicleType": "",
                "series": "",
                "cab": "",
                "brakes": "",
                "manufacturer": "",
                "plant": "",
            },
            "specs": [],
        },
        "missingFields": [],
        "warnings": [],
    }


def test_fields_the_vin_did_not_return_are_listed_as_missing(monkeypatch):
    # Caso real: un International 2011 trae año y motor, pero no marca ni modelo.
    _nhtsa(monkeypatch, result={**DECODED, "make": "", "model": None})

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    assert response.status_code == 200
    assert response.json()["vehicle"]["make"] == ""
    assert response.json()["vehicle"]["model"] == ""
    assert response.json()["missingFields"] == ["make", "model"]


def test_invalid_check_digit_adds_a_warning(monkeypatch):
    _nhtsa(monkeypatch, result={**DECODED, "check_digit_valid": False})

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    assert response.status_code == 200
    assert response.json()["warnings"] == ["check_digit"]


def test_vehicle_without_make_or_engine_returns_404(monkeypatch):
    _nhtsa(
        monkeypatch,
        result={
            **DECODED,
            "make": "",
            "displacement_l": "",
            "engine_model": "",
        },
    )

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    assert response.status_code == 404
    assert response.json()["error"] == (
        "We couldn't identify this vehicle from its VIN. "
        "Use Year / Make / Model to find parts that fit."
    )


def test_engine_falls_back_to_engine_model_when_displacement_missing(monkeypatch):
    _nhtsa(monkeypatch, result={**DECODED, "displacement_l": None, "engine_model": "6.0L V8"})

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    assert response.json()["vehicle"]["engine"] == "6.0L V8"


def test_empty_results_returns_404(monkeypatch):
    _nhtsa(monkeypatch, result=None)

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    assert response.status_code == 404
    assert response.json()["error"] == "Vehicle not found"


def test_upstream_http_error_returns_502_vin_service_unavailable(monkeypatch):
    _nhtsa(monkeypatch, error=ProviderUnavailable("NHTSA responded 500"))

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    assert response.status_code == 502
    assert response.json()["error"] == "VIN service unavailable"


def test_network_failure_returns_502_vin_verification_failed(monkeypatch):
    _nhtsa(monkeypatch, error=ProviderError("NHTSA request failed"))

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    assert response.status_code == 502
    assert response.json()["error"] == "VIN verification failed"


def test_details_describe_the_vehicle_like_a_listing(monkeypatch):
    _nhtsa(
        monkeypatch,
        result={
            **DECODED,
            "displacement_l": "6.7",
            "engine_manufacturer": "Cummins Inc.",
            "engine_cylinders": "6",
            "engine_configuration": "In-Line",
            "turbo": "Yes",
            "drive_type": "4WD/4-Wheel Drive/4x4",
            "transmission_style": "Automatic",
            "transmission_speeds": "8",
            "body_class": "Pickup",
            "trim": "Laramie",
            "gvwr": "Class 3: 10,001 - 14,000 lb (4,536 - 6,350 kg)",
        },
    )

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    details = response.json()["vehicle"]["details"]
    assert {key: details[key] for key in ("engine", "drivetrain", "transmission")} == {
        "engine": "Cummins 6.7L I6 Turbodiesel",
        "drivetrain": "4WD",
        "transmission": "8-Spd Automatic",
    }
    assert details["body"] == "Pickup"
    assert details["trim"] == "Laramie"
    assert details["gvwr"] == "Class 3: 10,001 - 14,000 lb"


def test_details_add_plant_power_and_type(monkeypatch):
    _nhtsa(
        monkeypatch,
        result={
            **DECODED,
            "vehicle_type": "INCOMPLETE VEHICLE",
            "manufacturer": "NAVISTAR, INC.",
            "plant_city": "SPRINGFIELD",
            "plant_state": "OHIO",
            "plant_country": "UNITED STATES (USA)",
            "engine_hp": "220",
            "brake_system": "Air",
            "cab_type": "Regular/Standard",
        },
    )

    details = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN}).json()["vehicle"]["details"]

    assert details["vehicleType"] == "Incomplete Vehicle"
    assert details["manufacturer"] == "Navistar, Inc."
    assert details["plant"] == "Springfield, Ohio, United States"
    assert details["horsepower"] == "220 hp"
    assert details["brakes"] == "Air"
    assert details["cab"] == "Regular"


def test_details_name_the_engine_model_when_the_manufacturer_is_missing(monkeypatch):
    # Caso real: el International 2011 trae el modelo de motor pero no el fabricante.
    _nhtsa(
        monkeypatch,
        result={**DECODED, "displacement_l": "6.4", "engine_model": "International Maxxforce 7"},
    )

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    details = response.json()["vehicle"]["details"]
    assert details["engine"] == "International Maxxforce 7 6.4L Diesel"


def test_specs_list_every_field_with_data_except_ids_and_errors(monkeypatch):
    raw = {
        "VIN": VALID_VIN,
        "ModelYear": "2011",
        "MakeID": "1028",
        "DisplacementCC": "6400.0",
        "EngineHP_to": "300",
        "NCSABodyType": "Cab-Chassis",
        "ErrorText": "1 - Check Digit",
    }
    _nhtsa(monkeypatch, result={**DECODED, "raw": raw})

    specs = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN}).json()["vehicle"]["specs"]

    assert specs == [
        {"label": "Model Year", "value": "2011"},
        {"label": "Displacement CC", "value": "6400.0"},
        {"label": "Engine HP to", "value": "300"},
        {"label": "NCSA Body Type", "value": "Cab-Chassis"},
    ]
