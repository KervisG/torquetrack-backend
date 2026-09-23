"""Tests de `POST /api/shipping/rates`.

La API REST real de EasyPost nunca se llama: se parchea su adaptador,
`apps.integrations.shipping.easypost.get_rates`, con el dict plano que
devuelve, y nunca se usa un `EASYPOST_API_KEY` real. El request HTTP y el
mapeo de cada tarifa se prueban en `apps/integrations/tests/test_easypost.py`.
"""

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Product
from apps.integrations.exceptions import ProviderError

PRODUCT_ID = "gm-65-injection-pump-dorman-502550"
GET_RATES = "apps.integrations.shipping.easypost.get_rates"


def _insert_product(product_id=PRODUCT_ID, data=None):
    Product.objects.create(id=product_id, data=data or {}, active=True)


def _rate(rate_id, carrier, service, rate, delivery_days, guaranteed=False):
    return {
        "id": rate_id,
        "carrier": carrier,
        "service": service,
        "rate": rate,
        "delivery_days": delivery_days,
        "guaranteed": guaranteed,
    }


def _fake_easypost(monkeypatch, shipment_id="shp_1", rates=()):
    captured = {}

    def _get_rates(**kwargs):
        captured.update(kwargs)
        return {"shipment_id": shipment_id, "rates": list(rates)}

    monkeypatch.setattr(GET_RATES, _get_rates)
    return captured


@pytest.mark.django_db
def test_returns_not_configured_when_no_api_key(settings, monkeypatch):
    settings.EASYPOST_API_KEY = ""

    def _boom(**kwargs):
        raise AssertionError("EasyPost must not be called without a key")

    monkeypatch.setattr(GET_RATES, _boom)

    response = APIClient().post("/api/shipping/rates/", {}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert "EASYPOST_API_KEY" in body["message"]
    # `.env.local` era el archivo de Next.js; Django lee el entorno del servidor.
    assert ".env.local" not in body["message"]


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

    captured = _fake_easypost(monkeypatch)

    response = APIClient().post(
        "/api/shipping/rates/", {"productId": PRODUCT_ID, "to": {"zip": "30301"}}, format="json"
    )

    assert response.status_code == 200
    parcel = captured["parcel"]
    assert captured["to_address"] == {"zip": "30301"}
    assert captured["from_address"]["country"] == "US"
    # shippingWeight=2 -> 2*16=32oz desde el producto; luego el chequeo <50
    # vuelve a multiplicar (comportamiento intencional, ver
    # `get_shipping_rates`) -> 32*16=512.
    assert parcel["weight"] == 512
    assert parcel["length"] == 14


@pytest.mark.django_db
def test_returns_502_on_easypost_error(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"

    def _fail(**kwargs):
        raise ProviderError("Invalid address")

    monkeypatch.setattr(GET_RATES, _fail)

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
        _rate("rate_ground", "USPS", "Ground Advantage", 8.5, 5),
        _rate("rate_overnight", "USPS", "Priority Mail Express", 35.0, 1, guaranteed=True),
        _rate("rate_2day", "UPS", "UPS 2nd Day Air", 15.0, 2),
    ]
    _fake_easypost(monkeypatch, shipment_id="shp_2", rates=rates)

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

    captured = _fake_easypost(monkeypatch, shipment_id="shp_3")

    response = APIClient().post(
        "/api/shipping/rates/",
        {"parcel": {"weight": 60, "length": 12, "width": 10, "height": 6}, "to": {"zip": "30301"}},
        format="json",
    )

    assert response.status_code == 200
    assert captured["parcel"]["weight"] == 60
