"""IP del cliente con la que se agrupan los throttles (`get_client_ip`).

Sin configurar nada manda `REMOTE_ADDR` y nunca se lee `X-Forwarded-For`.
Detrás de un proxy que no es Cloudflare, `NUM_PROXIES` (el de DRF) dice
cuántos proxies de confianza agregan su entrada al final del header: se toma
la que escribió el más externo y se ignora lo que el cliente haya puesto
antes. `CLIENT_IP_HEADER` gana sobre todo lo anterior. Sin base de datos ni
proveedores.
"""
import pytest
from django.conf import settings as django_settings
from rest_framework.test import APIRequestFactory

from apps.authentication.utils.throttling import get_client_ip


def _request(**meta):
    return APIRequestFactory().get("/probe/", **meta)


@pytest.fixture
def num_proxies(settings):
    def apply(value):
        # Se reemplaza el dict entero para que `api_settings` se recargue.
        settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": value}

    return apply


def test_default_config_does_not_trust_x_forwarded_for(settings):
    settings.CLIENT_IP_HEADER = ""
    assert django_settings.REST_FRAMEWORK["NUM_PROXIES"] == 0
    request = _request(REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="198.51.100.7")

    assert get_client_ip(request) == "10.0.0.5"


def test_one_trusted_proxy_uses_the_entry_it_appended(num_proxies, settings):
    settings.CLIENT_IP_HEADER = ""
    num_proxies(1)
    request = _request(REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="203.0.113.9")

    assert get_client_ip(request) == "203.0.113.9"


def test_one_trusted_proxy_ignores_spoofed_leading_entries(num_proxies, settings):
    settings.CLIENT_IP_HEADER = ""
    num_proxies(1)
    request = _request(
        REMOTE_ADDR="10.0.0.5",
        HTTP_X_FORWARDED_FOR="1.1.1.1, 8.8.8.8, 203.0.113.9",
    )

    assert get_client_ip(request) == "203.0.113.9"


def test_two_trusted_proxies_skip_the_inner_proxy_entry(num_proxies, settings):
    settings.CLIENT_IP_HEADER = ""
    num_proxies(2)
    request = _request(
        REMOTE_ADDR="10.0.0.5",
        HTTP_X_FORWARDED_FOR="1.1.1.1, 203.0.113.9, 10.0.0.4",
    )

    assert get_client_ip(request) == "203.0.113.9"


def test_trusted_proxy_without_header_falls_back_to_remote_addr(num_proxies, settings):
    settings.CLIENT_IP_HEADER = ""
    num_proxies(1)

    assert get_client_ip(_request(REMOTE_ADDR="10.0.0.5")) == "10.0.0.5"


def test_client_ip_header_wins_over_num_proxies(num_proxies, settings):
    settings.CLIENT_IP_HEADER = "HTTP_CF_CONNECTING_IP"
    num_proxies(1)
    request = _request(
        REMOTE_ADDR="10.0.0.5",
        HTTP_X_FORWARDED_FOR="203.0.113.9",
        HTTP_CF_CONNECTING_IP="198.51.100.3",
    )

    assert get_client_ip(request) == "198.51.100.3"
