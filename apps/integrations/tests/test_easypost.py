import base64

import pytest
import requests

from apps.integrations.exceptions import ProviderError, ProviderNotConfigured
from apps.integrations.shipping import easypost
from apps.integrations.tests.support import FakeResponse, RecordingPost

ARGS = {
    "to_address": {"zip": "30301"},
    "from_address": {"zip": "34241", "country": "US"},
    "parcel": {"weight": 60, "length": 12, "width": 10, "height": 6},
}


def test_not_configured_raises_without_calling_the_provider(settings, monkeypatch):
    settings.EASYPOST_API_KEY = ""

    def _boom(*args, **kwargs):
        raise AssertionError("EasyPost must not be called without a key")

    monkeypatch.setattr("apps.integrations.shipping.easypost.requests.post", _boom)

    assert easypost.is_configured() is False
    with pytest.raises(ProviderNotConfigured):
        easypost.get_rates(**ARGS)


def test_builds_the_shipment_request_and_maps_rates(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    post = RecordingPost(
        FakeResponse(
            {
                "id": "shp_1",
                "rates": [
                    {
                        "id": "rate_1",
                        "carrier": "USPS",
                        "service": "Ground Advantage",
                        "rate": "8.50",
                        "delivery_days": 5,
                        "delivery_date_guaranteed": False,
                    }
                ],
            }
        )
    )
    monkeypatch.setattr("apps.integrations.shipping.easypost.requests.post", post)

    result = easypost.get_rates(**ARGS)

    assert result == {
        "shipment_id": "shp_1",
        "rates": [
            {
                "id": "rate_1",
                "carrier": "USPS",
                "service": "Ground Advantage",
                "rate": 8.5,
                "delivery_days": 5,
                "guaranteed": False,
            }
        ],
    }
    call = post.calls[0]
    assert call["url"] == "https://api.easypost.com/v2/shipments"
    expected_auth = base64.b64encode(b"ep_test_fake:").decode()
    assert call["headers"]["Authorization"] == f"Basic {expected_auth}"
    assert call["json"] == {
        "shipment": {
            "to_address": {"zip": "30301"},
            "from_address": {"zip": "34241", "country": "US"},
            "parcel": {"weight": 60, "length": 12, "width": 10, "height": 6},
        }
    }


def test_provider_error_carries_the_easypost_message(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    response = FakeResponse({"error": {"message": "Invalid address"}}, ok=False, status_code=422)
    monkeypatch.setattr(
        "apps.integrations.shipping.easypost.requests.post", RecordingPost(response)
    )

    with pytest.raises(ProviderError, match="Invalid address"):
        easypost.get_rates(**ARGS)


def test_error_without_message_uses_generic_text(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    response = FakeResponse(ok=False, status_code=500, invalid_json=True)
    monkeypatch.setattr(
        "apps.integrations.shipping.easypost.requests.post", RecordingPost(response)
    )

    with pytest.raises(ProviderError, match="EasyPost rate request failed"):
        easypost.get_rates(**ARGS)


def test_network_error_raises_provider_error(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"

    def _raise(*args, **kwargs):
        raise requests.ConnectionError("network unreachable")

    monkeypatch.setattr("apps.integrations.shipping.easypost.requests.post", _raise)

    with pytest.raises(ProviderError, match="EasyPost rate request failed"):
        easypost.get_rates(**ARGS)
