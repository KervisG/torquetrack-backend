import pytest
import requests

from apps.integrations.exceptions import ProviderError, ProviderNotConfigured
from apps.integrations.tax import taxjar
from apps.integrations.tests.support import FakeResponse, RecordingPost

ARGS = {
    "from_zip": "34241",
    "to_state": "CA",
    "to_zip": "90001",
    "to_city": "Los Angeles",
    "to_street": "1 Main St",
    "amount": 100.0,
    "shipping": 10.0,
}


def test_not_configured_raises_without_calling_the_provider(settings, monkeypatch):
    settings.TAXJAR_API_KEY = ""

    def _boom(*args, **kwargs):
        raise AssertionError("TaxJar must not be called without a key")

    monkeypatch.setattr("apps.integrations.tax.taxjar.requests.post", _boom)

    assert taxjar.is_configured() is False
    with pytest.raises(ProviderNotConfigured):
        taxjar.calculate_tax(**ARGS)


def test_builds_the_request_and_maps_the_tax_block(settings, monkeypatch):
    settings.TAXJAR_API_KEY = "tj_test_fake"
    post = RecordingPost(FakeResponse({"tax": {"amount_to_collect": 7.35, "rate": "0.0735"}}))
    monkeypatch.setattr("apps.integrations.tax.taxjar.requests.post", post)

    result = taxjar.calculate_tax(**ARGS)

    assert result == {"amount_to_collect": 7.35, "rate": 0.0735}
    call = post.calls[0]
    assert call["url"] == "https://api.taxjar.com/v2/taxes"
    assert call["headers"]["Authorization"] == "Bearer tj_test_fake"
    assert call["json"] == {
        "from_country": "US",
        "from_zip": "34241",
        "to_country": "US",
        "to_state": "CA",
        "to_zip": "90001",
        "to_city": "Los Angeles",
        "to_street": "1 Main St",
        "amount": 100.0,
        "shipping": 10.0,
    }


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse({"error": "Bad Request"}, ok=False, status_code=400),
        FakeResponse(ok=True, invalid_json=True),
    ],
)
def test_bad_responses_raise_provider_error(settings, monkeypatch, response):
    settings.TAXJAR_API_KEY = "tj_test_fake"
    monkeypatch.setattr("apps.integrations.tax.taxjar.requests.post", RecordingPost(response))

    with pytest.raises(ProviderError):
        taxjar.calculate_tax(**ARGS)


def test_network_error_raises_provider_error(settings, monkeypatch):
    settings.TAXJAR_API_KEY = "tj_test_fake"

    def _raise(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("apps.integrations.tax.taxjar.requests.post", _raise)

    with pytest.raises(ProviderError):
        taxjar.calculate_tax(**ARGS)


def test_decimal_amounts_are_sent_as_json_numbers(settings, monkeypatch):
    # El dominio calcula en `Decimal`; `requests` no sabe serializarlo.
    from decimal import Decimal

    settings.TAXJAR_API_KEY = "tj_test_fake"
    post = RecordingPost(FakeResponse({"tax": {"amount_to_collect": 1, "rate": 0.06}}))
    monkeypatch.setattr("apps.integrations.tax.taxjar.requests.post", post)

    taxjar.calculate_tax(**{**ARGS, "amount": Decimal("120.50"), "shipping": Decimal("5.00")})

    sent = post.calls[0]["json"]
    assert sent["amount"] == 120.5 and isinstance(sent["amount"], float)
    assert sent["shipping"] == 5.0 and isinstance(sent["shipping"], float)
