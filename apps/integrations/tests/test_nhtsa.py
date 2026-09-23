"""Adaptador de NHTSA vPIC (`apps.integrations.vehicles.nhtsa`).

La llamada HTTP se mockea con `responses`. Los nombres de campo y el
envoltorio `{Results: [...]}` copian el formato real de
`DecodeVinValuesExtended` (documentación de https://vpic.nhtsa.dot.gov).
"""
import pytest
import responses
from requests.exceptions import ConnectionError as RequestsConnectionError

from apps.integrations.exceptions import ProviderError, ProviderUnavailable
from apps.integrations.vehicles import nhtsa

VALID_VIN = "1FTSW21P34EB12345"
NHTSA_URL = (
    f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/"
    f"{VALID_VIN}?format=json"
)


@responses.activate
def test_maps_the_first_result():
    responses.add(
        responses.GET,
        NHTSA_URL,
        json={
            "Count": 1,
            "Results": [
                {
                    "ModelYear": "2004",
                    "Make": "FORD",
                    "Model": "F-250",
                    "DisplacementL": "6.0",
                    "EngineModel": "POWER STROKE",
                    "FuelTypePrimary": "Diesel",
                }
            ],
        },
        status=200,
    )

    assert nhtsa.decode_vin(VALID_VIN) == {
        "model_year": "2004",
        "make": "FORD",
        "model": "F-250",
        "displacement_l": "6.0",
        "engine_model": "POWER STROKE",
        "fuel_type": "Diesel",
    }


@responses.activate
def test_empty_results_return_none():
    responses.add(responses.GET, NHTSA_URL, json={"Results": []}, status=200)

    assert nhtsa.decode_vin(VALID_VIN) is None


@responses.activate
def test_http_error_raises_provider_unavailable():
    responses.add(responses.GET, NHTSA_URL, json={"error": "boom"}, status=500)

    with pytest.raises(ProviderUnavailable):
        nhtsa.decode_vin(VALID_VIN)


@responses.activate
def test_network_failure_raises_provider_error():
    responses.add(responses.GET, NHTSA_URL, body=RequestsConnectionError("unreachable"))

    with pytest.raises(ProviderError) as excinfo:
        nhtsa.decode_vin(VALID_VIN)
    assert not isinstance(excinfo.value, ProviderUnavailable)


@responses.activate
def test_invalid_json_raises_provider_error():
    responses.add(responses.GET, NHTSA_URL, body="<html>", status=200)

    with pytest.raises(ProviderError):
        nhtsa.decode_vin(VALID_VIN)
