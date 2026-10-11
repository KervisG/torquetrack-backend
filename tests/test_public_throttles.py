"""Rate limit de las rutas públicas que cuestan: checkout y pago de una
cotización (sesión de Stripe y pedido), solicitud de cotización (fila y dos
correos), PDF de la cotización (WeasyPrint), tarifas de envío (EasyPost),
impuesto (TaxJar), decodificación de VIN (NHTSA) y fitment.

Cada ruta responde 429 con `{"error": ...}` y `Retry-After` al pasar su tope,
por IP del cliente. El webhook de Stripe NO tiene throttle: Stripe reintenta y
la firma ya lo protege; perder un evento dejaría un pago sin reconciliar.
El último test recorre el URLconf y exige que toda view `AllowAny` declare
`throttle_classes` o figure, con su motivo, en `UNTHROTTLED_PUBLIC_VIEWS`.

Los rates se fijan en la clase (`THROTTLE_RATES` se resuelve al importar).
Ningún proveedor responde: los adaptadores quedan parcheados para lanzar
`AssertionError` y el throttle corta antes de la view.
"""
import pytest
from django.core.cache import cache
from rest_framework.permissions import AllowAny
from rest_framework.test import APIClient

from apps.authentication.utils import throttling
from apps.checkout.views.webhooks import StripeWebhookView
from tests.fakes import forbid_resend
from tests.test_view_permissions import _drf_view_class, _url_patterns

LIMIT = 2


def _forbidden(*args, **kwargs):
    raise AssertionError("No provider may be called from a throttle test")


@pytest.fixture(autouse=True)
def _clear_throttle_history(db):
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _no_providers(monkeypatch):
    forbid_resend(monkeypatch)
    for target in (
        "apps.integrations.payments.stripe.create_checkout_session",
        "apps.integrations.shipping.easypost.get_rates",
        "apps.integrations.tax.taxjar.calculate_tax",
        "apps.integrations.vehicles.nhtsa.decode_vin",
        "apps.quotes.views.pdf.render_quote_pdf_bytes",
    ):
        monkeypatch.setattr(target, _forbidden)


# (método, ruta, body, clase de throttle)
THROTTLED_ROUTES = [
    ("post", "/api/checkout/", {}, "CheckoutRateThrottle"),
    ("post", "/api/quote/request/", {}, "QuoteRequestRateThrottle"),
    ("post", "/api/quote/public/missing-token/checkout/", {}, "QuoteCheckoutRateThrottle"),
    ("get", "/api/quote/public/missing-token/pdf/", None, "QuotePdfRateThrottle"),
    ("post", "/api/shipping/rates/", {}, "ShippingRatesRateThrottle"),
    ("post", "/api/tax/estimate/", {}, "TaxEstimateRateThrottle"),
    ("get", "/api/vin/decode/", None, "VinDecodeRateThrottle"),
    ("post", "/api/fitment/check/", {}, "FitmentCheckRateThrottle"),
]


def _send(client, method, path, body, client_ip):
    if method == "get":
        return client.get(path, REMOTE_ADDR=client_ip)
    return client.post(path, body, format="json", REMOTE_ADDR=client_ip)


@pytest.mark.django_db
@pytest.mark.parametrize(("method", "path", "body", "throttle_name"), THROTTLED_ROUTES)
def test_public_route_answers_429_after_its_limit(
    monkeypatch, settings, method, path, body, throttle_name
):
    settings.STRIPE_SECRET_KEY = ""
    monkeypatch.setattr(getattr(throttling, throttle_name), "rate", f"{LIMIT}/min", raising=False)
    client = APIClient()

    for _ in range(LIMIT):
        assert _send(client, method, path, body, "203.0.113.10").status_code != 429

    blocked = _send(client, method, path, body, "203.0.113.10")

    assert blocked.status_code == 429
    assert set(blocked.json()) == {"error"}
    assert blocked.json()["error"].startswith("Request was throttled")
    assert int(blocked["Retry-After"]) > 0


@pytest.mark.django_db
@pytest.mark.parametrize(("method", "path", "body", "throttle_name"), THROTTLED_ROUTES)
def test_public_route_limit_is_per_client_ip(
    monkeypatch, settings, method, path, body, throttle_name
):
    settings.STRIPE_SECRET_KEY = ""
    monkeypatch.setattr(getattr(throttling, throttle_name), "rate", "1/min", raising=False)
    client = APIClient()

    assert _send(client, method, path, body, "203.0.113.20").status_code != 429
    assert _send(client, method, path, body, "203.0.113.20").status_code == 429
    assert _send(client, method, path, body, "203.0.113.21").status_code != 429


def test_stripe_webhook_declares_no_throttle():
    # Explícito y vacío: un `DEFAULT_THROTTLE_CLASSES` futuro tampoco lo alcanza.
    assert StripeWebhookView.throttle_classes == []
    assert StripeWebhookView().get_throttles() == []


@pytest.mark.django_db
def test_stripe_webhook_is_never_throttled(settings):
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test_fake"
    client = APIClient()

    statuses = {
        client.post(
            "/api/webhooks/stripe/",
            b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=bad",
        ).status_code
        for _ in range(30)
    }

    assert statuses == {400}


# Views `AllowAny` sin throttle, a propósito. Toda view nueva `AllowAny` tiene
# que declarar `throttle_classes` o sumarse acá con su motivo. El webhook de
# Stripe y el health check no figuran: declaran `throttle_classes = []`.
UNTHROTTLED_PUBLIC_VIEWS = {
    # Lecturas baratas del catálogo que el SPA pide en cada pantalla.
    "apps.catalog.views.storefront.ProductPublicViewSet",
    "apps.catalog.views.storefront.ApplicationPublicViewSet",
    # Sitemap para buscadores: una lectura del catálogo, sin proveedor.
    "apps.catalog.views.sitemap.SitemapView",
    # Carrito: una fila por sesión, el SPA lo sincroniza en cada cambio.
    "apps.cart.views.storefront.CartView",
    # Sesión y logout: sin proveedor ni trabajo pesado.
    "apps.authentication.views.SessionView",
    "apps.authentication.views.LogoutView",
    # Lecturas por token imposible de adivinar, sin proveedor.
    "apps.quotes.views.storefront.PublicQuoteDetailsView",
    # Exigen sesión (401 sin ella); `AllowAny` solo separa el 401 del 403/404.
    "apps.customers.views.storefront.AccountView",
    "apps.customers.views.storefront.AccountOrdersView",
    "apps.customers.views.storefront.AccountQuotesView",
    "apps.customers.views.storefront.AccountTaxExemptionView",
    "apps.customers.views.admin.AdminCustomerTaxExemptionView",
    "apps.customers.views.admin.AdminCustomerTaxStatusView",
    "apps.checkout.views.admin.AdminOrderDetailView",
    "apps.authorization.views.AdminUsersView",
    "apps.authorization.views.AdminUserDetailView",
    "apps.authorization.views.AdminRolesView",
    "apps.authorization.views.AdminRoleDetailView",
}


def _declares_throttles(cls) -> bool:
    return any(
        "throttle_classes" in vars(klass)
        for klass in cls.__mro__
        if not klass.__module__.startswith("rest_framework")
    )


def test_every_public_view_declares_throttle_classes_or_is_allowlisted():
    public = {
        f"{cls.__module__}.{cls.__qualname__}"
        for _, callback in _url_patterns()
        if (cls := _drf_view_class(callback)) is not None
        and AllowAny in getattr(cls, "permission_classes", [])
        and not _declares_throttles(cls)
    }

    assert sorted(public - UNTHROTTLED_PUBLIC_VIEWS) == []
    # La lista no guarda views que ya no existen o que ya tienen throttle.
    assert sorted(UNTHROTTLED_PUBLIC_VIEWS - public) == []
