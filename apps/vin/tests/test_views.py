"""Tests de `GET /api/vin/decode`.

Mocking: NHTSA se falsea en su adaptador,
`apps.integrations.vehicles.nhtsa.decode_vin`, con el dict plano que
devuelve. El formato real de vPIC y el mapeo HTTP se prueban en
`apps/integrations/tests/test_nhtsa.py`.
"""
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
}


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
        }
    }


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
