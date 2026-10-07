"""Exportación del catálogo del panel (`GET /api/admin/products/export/`).

El ZIP es una copia que se vuelve a cargar en otro servidor con
`import_catalog --products products.json --applications applications.json`:
`products.json` tiene la misma forma que la semilla más `active` (que
`import_catalog` lleva a la columna) y `applicationIds` sale de
`ProductFitment`, la fuente de verdad del fitment. Las imágenes locales
(`/static/image/<archivo>`) viajan en `image/` para copiarlas a `static/image/`
del repo destino; una URL externa queda en el JSON y no se descarga.

Sin `costs.view` los campos de `HIDDEN_WITHOUT_COSTS` no salen, así que esa
copia no sirve para restaurar costos ni proveedores."""
from __future__ import annotations

import io
import json
import posixpath
import zipfile
from datetime import date

from django.contrib.staticfiles import finders

from apps.catalog.models import Product
from apps.catalog.services.admin import serialize_admin_product
from apps.catalog.services.fitment import application_codes, list_applications

# Prefijo con el que `data.image` apunta a un archivo de `static/image/`.
LOCAL_IMAGE_PREFIX = "/static/image/"
MISSING_IMAGES_FILE = "missing-images.txt"


def export_filename(day: date) -> str:
    return f"torquetrack-catalog-{day.isoformat()}.zip"


def _export_product(product: Product, *, can_view_costs: bool) -> dict:
    data = serialize_admin_product(product.data or {}, can_view_costs=can_view_costs)
    # El slug es de la columna y se regenera al importar; un `slug` en `data`
    # no se usa nunca.
    data.pop("slug", None)
    data["id"] = product.pk
    codes = application_codes(product)
    if codes:
        data["applicationIds"] = codes
    else:
        # Un `applicationIds` viejo de `data` rearmaría al importar un fitment
        # que el panel ya quitó.
        data.pop("applicationIds", None)
    data["active"] = product.active
    return data


def local_image_path(image) -> str | None:
    """Ruta relativa a los estáticos (`image/<archivo>`) o `None` si la imagen
    no es local o intenta salir de `image/` (`..`, barras invertidas)."""
    if not isinstance(image, str) or not image.startswith(LOCAL_IMAGE_PREFIX):
        return None
    if "\\" in image:
        return None
    relative = posixpath.normpath(image.removeprefix("/static/"))
    if not relative.startswith("image/"):
        return None
    return relative


def _json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build_catalog_export(*, can_view_costs: bool) -> bytes:
    """Incluye activos e inactivos, igual que el listado del panel."""
    products = [
        _export_product(product, can_view_costs=can_view_costs)
        for product in Product.objects.prefetch_related("applications").order_by("id")
    ]

    images: dict[str, str] = {}
    missing: list[str] = []
    for product in products:
        image = product.get("image")
        if not isinstance(image, str) or not image.startswith(LOCAL_IMAGE_PREFIX):
            continue
        relative = local_image_path(image)
        if relative in images:
            continue
        found = finders.find(relative) if relative else None
        if found:
            images[relative] = found
        else:
            missing.append(f"{product['id']}: {image}")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("products.json", _json_bytes(products))
        archive.writestr("applications.json", _json_bytes(list_applications()))
        for relative, path in sorted(images.items()):
            archive.write(path, arcname=relative)
        if missing:
            archive.writestr(MISSING_IMAGES_FILE, "\n".join(missing) + "\n")
    return buffer.getvalue()
