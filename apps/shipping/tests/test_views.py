"""`POST /api/shipping/rates` (task 7.5), pinned against
`app/api/shipping/rates/route.ts`.

The real EasyPost REST API is never called: `requests.post` is monkeypatched
at `apps.shipping.services.requests.post`, and no real `EASYPOST_API_KEY` is
ever used.
"""

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Product

PRODUCT_ID = "gm-65-injection-pump-dorman-502550"


def _insert_product(product_id=PRODUCT_ID, data=None):
    Product.objects.create(id=product_id, data=data or {}, active=True)


class _FakeResponse:
    def __init__(self, payload, ok=True, status_code=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._payload


@pytest.mark.django_db
def test_returns_not_configured_when_no_api_key(settings):
    settings.EASYPOST_API_KEY = ""

    response = APIClient().post("/api/shipping/rates/", {}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert "EASYPOST_API_KEY" in body["message"]


@pytest.mark.django_db
def test_returns_400_when_no_parcel_or_product(settings):
    settings.EASYPOST_API_KEY = "ep_test_fake"

    response = APIClient().post("/api/shipping/rates/", {"to": {"zip": "30301"}}, format="json")

    assert response.status_code == 400
    assert response.json()["error"] == "Parcel information required"


@pytest.mark.django_db
def test_builds_parcel_from_product_when_no_parcel_given(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(data={"shippingWeight": 2, "packageLength": 14})

    captured = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse({"id": "shp_1", "rates": []})

    monkeypatch.setattr("apps.shipping.services.requests.post", _fake_post)

    response = APIClient().post(
        "/api/shipping/rates/", {"productId": PRODUCT_ID, "to": {"zip": "30301"}}, format="json"
    )

    assert response.status_code == 200
    parcel = captured["payload"]["shipment"]["parcel"]
    # shippingWeight=2 -> 2*16=32oz built from product, then the <50 check
    # multiplies again (verbatim legacy behavior, see route.ts) -> 32*16=512.
    assert parcel["weight"] == 512
    assert parcel["length"] == 14


@pytest.mark.django_db
def test_returns_502_on_easypost_error(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"

    def _fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse({"error": {"message": "Invalid address"}}, ok=False, status_code=422)

    monkeypatch.setattr("apps.shipping.services.requests.post", _fake_post)

    response = APIClient().post(
        "/api/shipping/rates/",
        {"parcel": {"weight": 60, "length": 12, "width": 10, "height": 6}, "to": {"zip": "30301"}},
        format="json",
    )

    assert response.status_code == 502
    assert response.json()["error"] == "Invalid address"


@pytest.mark.django_db
def test_picks_ground_second_day_and_overnight_rates(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"

    rates = [
        {
            "id": "rate_ground",
            "carrier": "USPS",
            "service": "Ground Advantage",
            "rate": "8.50",
            "delivery_days": 5,
            "delivery_date_guaranteed": False,
        },
        {
            "id": "rate_overnight",
            "carrier": "USPS",
            "service": "Priority Mail Express",
            "rate": "35.00",
            "delivery_days": 1,
            "delivery_date_guaranteed": True,
        },
        {
            "id": "rate_2day",
            "carrier": "UPS",
            "service": "UPS 2nd Day Air",
            "rate": "15.00",
            "delivery_days": 2,
            "delivery_date_guaranteed": False,
        },
    ]

    def _fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse({"id": "shp_2", "rates": rates})

    monkeypatch.setattr("apps.shipping.services.requests.post", _fake_post)

    response = APIClient().post(
        "/api/shipping/rates/",
        {"parcel": {"weight": 60, "length": 12, "width": 10, "height": 6}, "to": {"zip": "30301"}},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["shipmentId"] == "shp_2"
    assert body["ground"]["id"] == "rate_ground"
    assert body["ground"]["rate"] == 8.5
    assert body["secondDay"]["id"] == "rate_2day"
    assert body["overnight"]["id"] == "rate_overnight"
    assert body["overnight"]["guaranteed"] is True


@pytest.mark.django_db
def test_does_not_double_convert_weight_at_or_above_50(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"

    captured = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse({"id": "shp_3", "rates": []})

    monkeypatch.setattr("apps.shipping.services.requests.post", _fake_post)

    response = APIClient().post(
        "/api/shipping/rates/",
        {"parcel": {"weight": 60, "length": 12, "width": 10, "height": 6}, "to": {"zip": "30301"}},
        format="json",
    )

    assert response.status_code == 200
    assert captured["payload"]["shipment"]["parcel"]["weight"] == 60
