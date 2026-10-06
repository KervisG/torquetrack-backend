"""Sitemap XML del storefront para buscadores.

Las URLs son del SPA (`app_url`), no del backend: Nginx sirve este documento en
`{APP_URL}/sitemap.xml` reenviándolo a `/api/sitemap.xml`. Solo entran las
páginas públicas indexables; el carrito, el checkout, la cuenta y los enlaces
por token (`/quote/<token>`) quedan fuera a propósito.
"""
from xml.sax.saxutils import escape

from django.utils import timezone

from apps.catalog.models import Product
from apps.common.links import app_url

# Rutas fijas del SPA (`src/routes.tsx` del frontend). El inicio es el catálogo.
STATIC_SITEMAP_PATHS = (
    "/",
    "/quote",
    "/policies",
    "/policies/shipping",
    "/policies/returns",
    "/policies/privacy",
    "/policies/terms",
)

PRODUCT_PATH = "/product/{}"


def _url_entry(location: str, lastmod: str | None = None) -> str:
    lastmod_tag = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
    return f"<url><loc>{escape(location)}</loc>{lastmod_tag}</url>"


def build_sitemap_xml() -> str:
    entries = [_url_entry(app_url(path)) for path in STATIC_SITEMAP_PATHS]
    products = (
        Product.objects.filter(active=True).order_by("slug").values_list("slug", "updated_at")
    )
    for slug, updated_at in products.iterator():
        lastmod = timezone.localtime(updated_at).date().isoformat() if updated_at else None
        entries.append(_url_entry(app_url(PRODUCT_PATH.format(slug)), lastmod))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{''.join(entries)}"
        "</urlset>\n"
    )
