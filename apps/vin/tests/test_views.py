"""`GET /api/vin/decode` (task 4.3), pinned against
`app/api/vin/decode/route.ts`.

The real NHTSA vPIC HTTP call is mocked with `responses` (per the design's
testing strategy). Field names and the general `{Results: [...]}` envelope
shape below mirror the actual `DecodeVinValuesExtended` response format
(https://vpic.nhtsa.dot.gov docs) — this is NOT a live call, but the mocked
payload shape matches the real API's documented contract, not an invented
one.
"""
import responses
from requests.exceptions import ConnectionError as RequestsConnectionError
from rest_framework.test import APIClient

VALID_VIN = "1FTSW21P34EB12345"
NHTSA_URL = (
    f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/"
    f"{VALID_VIN}?format=json"
)


def test_malformed_vin_returns_400():
    response = APIClient().get("/api/vin/decode/", {"vin": "TOO-SHORT"})

    assert response.status_code == 400
    assert response.json()["error"] == "VIN must contain 17 valid characters"


def test_vin_with_excluded_characters_i_o_q_returns_400():
    # VIN charset never contains I, O, or Q — matches the Next.js regex
    # `[A-HJ-NPR-Z0-9]{17}` exactly.
    response = APIClient().get("/api/vin/decode/", {"vin": "IOQ" + "1" * 14})

    assert response.status_code == 400


@responses.activate
def test_valid_vin_returns_decoded_vehicle():
    responses.add(
        responses.GET,
        NHTSA_URL,
        json={
            "Count": 1,
            "Message": "Results returned successfully",
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

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN.lower()})

    assert response.status_code == 200
    assert response.json() == {
        "vehicle": {
            "vin": VALID_VIN,
            "year": "2004",
            "make": "FORD",
            "model": "F-250",
            "engine": "6.0",
            "engineModel": "POWER STROKE",
            "fuelType": "Diesel",
        }
    }


@responses.activate
def test_engine_falls_back_to_engine_model_when_displacement_missing():
    responses.add(
        responses.GET,
        NHTSA_URL,
        json={"Results": [{"ModelYear": "2004", "Make": "FORD", "EngineModel": "6.0L V8"}]},
        status=200,
    )

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    assert response.json()["vehicle"]["engine"] == "6.0L V8"


@responses.activate
def test_empty_results_returns_404():
    responses.add(responses.GET, NHTSA_URL, json={"Results": []}, status=200)

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    assert response.status_code == 404
    assert response.json()["error"] == "Vehicle not found"


@responses.activate
def test_upstream_5xx_returns_502_vin_service_unavailable():
    responses.add(responses.GET, NHTSA_URL, json={"error": "boom"}, status=500)

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    assert response.status_code == 502
    assert response.json()["error"] == "VIN service unavailable"


@responses.activate
def test_network_failure_returns_502_vin_verification_failed():
    responses.add(
        responses.GET,
        NHTSA_URL,
        body=RequestsConnectionError("network unreachable"),
    )

    response = APIClient().get("/api/vin/decode/", {"vin": VALID_VIN})

    assert response.status_code == 502
    assert response.json()["error"] == "VIN verification failed"
