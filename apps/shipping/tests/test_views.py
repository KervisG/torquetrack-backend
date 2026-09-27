
import logging

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Product
from apps.integrations.exceptions import ProviderError
from apps.shipping.services import verify_shipping_selection

PRODUCT_ID = "gm-65-injection-pump-dorman-502550"
GET_RATES = "apps.integrations.shipping.easypost.get_rates"


def _insert_product(product_id=PRODUCT_ID, data=None, active=True):
    Product.objects.create(id=product_id, data=data or {}, active=active)


def _post_rates(body):
    return APIClient().post("/api/shipping/rates/", body, format="json")


def _items(*pairs):
    return [{"id": product_id, "qty": qty} for product_id, qty in pairs]


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

    response = _post_rates({})

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert "EASYPOST_API_KEY" in body["message"]


@pytest.mark.django_db
@pytest.mark.parametrize("items", [None, [], "p1", [{"qty": 1}], ["p1"]])
def test_returns_400_without_valid_items(settings, monkeypatch, items):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _fake_easypost(monkeypatch)
    body = {"to": {"zip": "30301"}}
    if items is not None:
        body["items"] = items

    response = _post_rates(body)

    assert response.status_code == 400
    assert response.json() == {"error": "Add at least one item to get shipping rates"}


@pytest.mark.django_db
@pytest.mark.parametrize("active", [True, False])
def test_returns_400_for_unknown_or_inactive_products(settings, monkeypatch, active):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(product_id="p_known", data={"shippingWeight": 2})
    _insert_product(product_id="p_other", data={"shippingWeight": 2}, active=active)

    def _boom(**kwargs):
        raise AssertionError("EasyPost must not be called with an unknown product")

    monkeypatch.setattr(GET_RATES, _boom)
    missing = "p_missing" if active else "p_other"

    response = _post_rates({"to": {"zip": "30301"}, "items": _items(("p_known", 1), (missing, 1))})

    assert response.status_code == 400
    assert response.json() == {"error": f"Product is not available: {missing}"}


@pytest.mark.django_db
def test_builds_parcel_from_the_items(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(
        product_id="p_pump",
        data={"shippingWeight": 25, "packageLength": 20, "packageWidth": 15, "packageHeight": 30},
    )
    _insert_product(
        product_id="p_sensor",
        data={"shippingWeight": 0.5, "lengthIn": 6, "widthIn": 18, "heightIn": 4},
    )
    captured = _fake_easypost(monkeypatch)

    response = _post_rates(
        {"to": {"zip": "30301"}, "items": _items(("p_pump", 2), ("p_sensor", 3))}
    )

    assert response.status_code == 200
    assert captured["to_address"] == {"zip": "30301"}
    assert captured["from_address"]["country"] == "US"
    # Peso: (25 lb × 2 + 0.5 lb × 3) × 16. Largo y ancho: el mayor de cada
    # uno. Alto: las cajas apiladas, cada una por su cantidad.
    assert captured["parcel"] == {
        "weight": (25 * 2 + 0.5 * 3) * 16,
        "length": 20,
        "width": 18,
        "height": 30 * 2 + 4 * 3,
    }


@pytest.mark.django_db
def test_ships_from_the_configured_zip(settings, monkeypatch):
    # El respaldo `34241` vive solo en settings: el service usa lo que haya.
    settings.EASYPOST_API_KEY = "ep_test_fake"
    settings.SHIP_FROM_ZIP = "33602"
    _insert_product()
    captured = _fake_easypost(monkeypatch)

    _post_rates({"to": {"zip": "30301"}, "items": _items((PRODUCT_ID, 1))})

    assert captured["from_address"] == {"zip": "33602", "country": "US"}


@pytest.mark.django_db
def test_ignores_a_parcel_sent_by_the_client(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(data={"shippingWeight": 25})
    captured = _fake_easypost(monkeypatch)

    response = _post_rates(
        {
            "to": {"zip": "30301"},
            "items": _items((PRODUCT_ID, 1)),
            "parcel": {"weight": 1, "length": 1, "width": 1, "height": 1},
        }
    )

    assert response.status_code == 200
    assert captured["parcel"]["weight"] == 25 * 16
    assert captured["parcel"]["length"] == 12


@pytest.mark.django_db
def test_repeated_ids_add_up(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(data={"shippingWeight": 1})
    captured = _fake_easypost(monkeypatch)

    _post_rates({"to": {"zip": "30301"}, "items": _items((PRODUCT_ID, 1), (PRODUCT_ID, 2))})

    assert captured["parcel"]["weight"] == 3 * 16


@pytest.mark.django_db
def test_quantity_is_clamped_like_the_checkout(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(data={"shippingWeight": 1, "packageHeight": 2})
    captured = _fake_easypost(monkeypatch)

    _post_rates({"to": {"zip": "30301"}, "items": _items((PRODUCT_ID, 500))})

    assert captured["parcel"]["weight"] == 99 * 16
    assert captured["parcel"]["height"] == 99 * 2


@pytest.mark.django_db
def test_weight_in_ounces_is_used_when_pounds_are_missing(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(data={"weightOz": 40})
    captured = _fake_easypost(monkeypatch)

    _post_rates({"to": {"zip": "30301"}, "items": _items((PRODUCT_ID, 1))})

    assert captured["parcel"]["weight"] == 40


@pytest.mark.django_db
def test_missing_weight_and_size_use_the_default_box_and_are_logged(
    settings, monkeypatch, caplog
):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(data={"shippingWeight": 0, "lengthIn": 0})
    captured = _fake_easypost(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="apps.shipping.services.rates"):
        _post_rates({"to": {"zip": "30301"}, "items": _items((PRODUCT_ID, 2))})

    assert captured["parcel"] == {"weight": 2 * 16, "length": 12, "width": 10, "height": 6 * 2}
    assert PRODUCT_ID in caplog.text


@pytest.mark.django_db
def test_parcel_weighs_at_least_one_pound(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(data={"weightOz": 4})
    captured = _fake_easypost(monkeypatch)

    _post_rates({"to": {"zip": "30301"}, "items": _items((PRODUCT_ID, 1))})

    assert captured["parcel"]["weight"] == 16


@pytest.mark.django_db
def test_easypost_error_returns_a_generic_502_and_logs_the_detail(settings, monkeypatch, caplog):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(data={"shippingWeight": 2})

    def _fail(**kwargs):
        raise ProviderError("Wrong API key for account acct_internal_123")

    monkeypatch.setattr(GET_RATES, _fail)

    with caplog.at_level("WARNING", logger="apps.shipping.services.rates"):
        response = _post_rates({"to": {"zip": "30301"}, "items": _items((PRODUCT_ID, 1))})

    assert response.status_code == 502
    assert response.json() == {
        "error": "Shipping rates are temporarily unavailable. Please try again."
    }
    assert "acct_internal_123" in caplog.text


@pytest.mark.django_db
def test_picks_ground_second_day_and_overnight_rates(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(data={"shippingWeight": 2})

    rates = [
        _rate("rate_ground", "USPS", "Ground Advantage", 8.5, 5),
        _rate("rate_overnight", "USPS", "Priority Mail Express", 35.0, 1, guaranteed=True),
        _rate("rate_2day", "UPS", "UPS 2nd Day Air", 15.0, 2),
    ]
    _fake_easypost(monkeypatch, shipment_id="shp_2", rates=rates)

    response = _post_rates({"to": {"zip": "30301"}, "items": _items((PRODUCT_ID, 1))})

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
def test_each_rate_carries_its_shipment_id(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _insert_product(data={"shippingWeight": 2})
    _fake_easypost(
        monkeypatch,
        shipment_id="shp_5",
        rates=[_rate("rate_ground", "USPS", "Ground Advantage", 8.5, 5)],
    )

    response = _post_rates({"to": {"zip": "30301"}, "items": _items((PRODUCT_ID, 1))})

    assert response.json()["ground"]["shipmentId"] == "shp_5"


def _quote_rates(settings, monkeypatch, zip_code="30301-1234"):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _fake_easypost(
        monkeypatch,
        shipment_id="shp_quoted",
        rates=[_rate("rate_ground", "USPS", "Ground Advantage", 8.5, 5)],
    )
    _insert_product(data={"shippingWeight": 2})
    _post_rates({"to": {"zip": zip_code}, "items": _items((PRODUCT_ID, 1))})


@pytest.mark.django_db
def test_verify_selection_returns_the_quoted_amount(settings, monkeypatch):
    _quote_rates(settings, monkeypatch)

    verified = verify_shipping_selection(
        {"shipmentId": "shp_quoted", "rateId": "rate_ground", "rate": 0.01},
        "30301",
        items=_items((PRODUCT_ID, 1)),
    )

    assert verified == {
        "shipmentId": "shp_quoted",
        "rateId": "rate_ground",
        "carrier": "USPS",
        "service": "Ground Advantage",
        "rate": 8.5,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "selection, zip_code",
    [
        ({"shipmentId": "shp_quoted", "rateId": "rate_forged"}, "30301"),
        ({"shipmentId": "shp_unknown", "rateId": "rate_ground"}, "30301"),
        ({"shipmentId": "shp_quoted", "rateId": "rate_ground"}, "90210"),
        ({"shipmentId": "shp_quoted", "rateId": "rate_ground"}, ""),
        ({"rate": 8.5}, "30301"),
        ("8.5", "30301"),
        (None, "30301"),
    ],
)
def test_verify_selection_rejects_unquoted_rates(settings, monkeypatch, selection, zip_code):
    _quote_rates(settings, monkeypatch)

    assert verify_shipping_selection(selection, zip_code, items=_items((PRODUCT_ID, 1))) is None


SELECTION = {"shipmentId": "shp_quoted", "rateId": "rate_ground"}


def _quote_two_products(settings, monkeypatch):
    settings.EASYPOST_API_KEY = "ep_test_fake"
    _fake_easypost(
        monkeypatch,
        shipment_id="shp_quoted",
        rates=[_rate("rate_ground", "USPS", "Ground Advantage", 8.5, 5)],
    )
    _insert_product(product_id="p_light", data={"shippingWeight": 1})
    _insert_product(product_id="p_heavy", data={"shippingWeight": 60})
    _post_rates({"to": {"zip": "30301"}, "items": _items(("p_light", 2), ("p_heavy", 1))})


@pytest.mark.django_db
@pytest.mark.parametrize(
    "items",
    [
        # Otro producto, otra cantidad, un ítem de más o uno de menos: el
        # paquete cotizado ya no es el que se paga.
        _items(("p_heavy", 3)),
        _items(("p_light", 2), ("p_heavy", 2)),
        _items(("p_light", 2), ("p_heavy", 1), (PRODUCT_ID, 1)),
        _items(("p_light", 2)),
        [],
        None,
        "p_light",
    ],
)
def test_verify_selection_rejects_items_other_than_the_quoted_ones(settings, monkeypatch, items):
    _quote_two_products(settings, monkeypatch)

    assert verify_shipping_selection(SELECTION, "30301", items=items) is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "items",
    [
        _items(("p_heavy", 1), ("p_light", 2)),
        _items(("p_light", 1), ("p_heavy", 1), ("p_light", 1)),
        [{"id": "p_light", "qty": "2"}, {"id": "p_heavy"}],
    ],
)
def test_verify_selection_accepts_the_same_items_in_any_order(settings, monkeypatch, items):
    _quote_two_products(settings, monkeypatch)

    assert verify_shipping_selection(SELECTION, "30301", items=items)["rate"] == 8.5
