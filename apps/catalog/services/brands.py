"""Marcas del panel: listar, crear, activar o desactivar y su logo.

Una marca es el nombre que llevan los productos en `manufacturer`. Ese texto
admite varias (`Alliant Power / Bosch`), así que el vínculo es por nombre, sin
distinguir mayúsculas, y no una FK. Desactivar una marca desactiva los
productos que la llevan: la tienda, el carrito y el checkout ya filtran por
`Product.active`, y así no hace falta otro filtro en cada consulta.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity
from apps.catalog.models import Brand, Product
from apps.catalog.services.images import (
    FILE_REQUIRED,
    FILE_TOO_LARGE,
    MAX_IMAGE_BYTES,
    STORAGE_FAILED,
    STORAGE_NOT_CONFIGURED,
    InvalidImage,
    process_image,
)
from apps.catalog.services.search import manufacturer_names
from apps.common.errors import error_payload
from apps.common.ids import random_id
from apps.integrations.exceptions import ProviderError, ProviderNotConfigured
from apps.integrations.storage import spaces

logger = logging.getLogger(__name__)

# Un logo se muestra chico: no hace falta el tamaño de una foto de producto.
MAX_LOGO_SIDE = 400

NAME_REQUIRED = "Brand name is required"
NAME_TAKEN = "A brand with this name already exists"
NAME_HAS_SEPARATOR = "A brand name cannot contain '/'"
ACTIVE_NOT_BOOLEAN = "active must be a boolean"
BRAND_NOT_FOUND = "Brand not found"


def _product_ids_by_brand() -> dict[str, list[str]]:
    """Ids de los productos de cada marca, por nombre en minúsculas. Cuenta
    activos e inactivos: el panel muestra todos."""
    ids: dict[str, list[str]] = {}
    rows = Product.objects.exclude(manufacturer__isnull=True).values_list("pk", "manufacturer")
    for product_id, manufacturer in rows:
        for name in {name.lower() for name in manufacturer_names(manufacturer)}:
            ids.setdefault(name, []).append(product_id)
    return ids


def _serialize(brand: Brand, product_count: int) -> dict:
    return {
        "id": brand.pk,
        "name": brand.name,
        "logo": brand.logo_url or None,
        "active": brand.active,
        "productCount": product_count,
    }


def _brand_payload(brand: Brand) -> dict:
    count = len(_product_ids_by_brand().get(brand.name.lower(), []))
    return {"ok": True, "brand": _serialize(brand, count)}


def _locked_brand(brand_id) -> Brand | None:
    return Brand.objects.select_for_update().filter(pk=brand_id).first()


def list_admin_brands() -> list[dict]:
    ids = _product_ids_by_brand()
    return [
        _serialize(brand, len(ids.get(brand.name.lower(), []))) for brand in Brand.objects.all()
    ]


def ensure_brands(manufacturer) -> None:
    """Crea las marcas de `manufacturer` que todavía no existen. Lo llaman las
    dos vías de carga de productos: el panel y `import_catalog`."""
    names = manufacturer_names(manufacturer)
    if not names:
        return
    existing = {name.lower() for name in Brand.objects.values_list("name", flat=True)}
    for name in names:
        if name.lower() not in existing:
            Brand.objects.create(name=name)
            existing.add(name.lower())


def create_admin_brand(payload: dict, actor_email: str) -> tuple[dict, int]:
    raw = payload.get("name")
    name = raw.strip() if isinstance(raw, str) else ""
    if not name:
        return error_payload(NAME_REQUIRED, "name"), 400
    if "/" in name:
        return error_payload(NAME_HAS_SEPARATOR, "name"), 400
    if Brand.objects.filter(name__iexact=name).exists():
        return error_payload(NAME_TAKEN, "name"), 400

    brand = Brand.objects.create(name=name)
    record_activity(
        actor=actor_email,
        action="BRAND_CREATED",
        entity_type="BRAND",
        entity_id=str(brand.pk),
        data={"name": name},
    )
    return _brand_payload(brand), 201


def set_admin_brand_active(brand_id, payload: dict, actor_email: str) -> tuple[dict, int]:
    active = payload.get("active")
    if not isinstance(active, bool):
        return error_payload(ACTIVE_NOT_BOOLEAN, "active"), 400

    with transaction.atomic():
        brand = _locked_brand(brand_id)
        if brand is None:
            return {"error": BRAND_NOT_FOUND}, 404
        product_ids = _product_ids_by_brand().get(brand.name.lower(), [])
        brand.active = active
        brand.save(update_fields=["active"])
        Product.objects.filter(pk__in=product_ids).update(active=active, updated_at=timezone.now())
        record_activity(
            actor=actor_email,
            action="BRAND_ACTIVATED" if active else "BRAND_DEACTIVATED",
            entity_type="BRAND",
            entity_id=str(brand.pk),
            data={"name": brand.name, "products": len(product_ids)},
        )
    return {"ok": True, "brand": _serialize(brand, len(product_ids))}, 200


def _delete_stored_logo(key: str) -> None:
    if not key:
        return
    try:
        spaces.delete(key)
    except ProviderError as exc:
        # La marca ya no lo usa: un objeto huérfano no rompe nada.
        logger.warning("Spaces delete of %s failed: %s", key, exc)


def set_admin_brand_logo(brand_id, upload, actor_email: str) -> tuple[dict, int]:
    if upload is None:
        return error_payload(FILE_REQUIRED, "file"), 400
    if upload.size > MAX_IMAGE_BYTES:
        return error_payload(FILE_TOO_LARGE, "file"), 400
    try:
        content, _width, _height = process_image(upload.read(), max_side=MAX_LOGO_SIDE)
    except InvalidImage as exc:
        return error_payload(str(exc), "file"), 400

    with transaction.atomic():
        brand = _locked_brand(brand_id)
        if brand is None:
            return {"error": BRAND_NOT_FOUND}, 404
        key = f"brands/{brand.pk}/{random_id('LOGO').lower()}.webp"
        try:
            url = spaces.upload(key=key, content=content, content_type="image/webp")
        except ProviderNotConfigured:
            return {"error": STORAGE_NOT_CONFIGURED}, 503
        except ProviderError as exc:
            logger.warning("Spaces upload for brand %s failed: %s", brand.pk, exc)
            return {"error": STORAGE_FAILED}, 502

        previous_key = brand.logo_key
        brand.logo_key = key
        brand.logo_url = url
        brand.save(update_fields=["logo_key", "logo_url"])
        record_activity(
            actor=actor_email,
            action="BRAND_LOGO_UPDATED",
            entity_type="BRAND",
            entity_id=str(brand.pk),
            data={"key": key},
        )
    _delete_stored_logo(previous_key)
    return _brand_payload(brand), 200


def remove_admin_brand_logo(brand_id, actor_email: str) -> tuple[dict, int]:
    with transaction.atomic():
        brand = _locked_brand(brand_id)
        if brand is None:
            return {"error": BRAND_NOT_FOUND}, 404
        previous_key = brand.logo_key
        brand.logo_key = ""
        brand.logo_url = ""
        brand.save(update_fields=["logo_key", "logo_url"])
        if previous_key:
            record_activity(
                actor=actor_email,
                action="BRAND_LOGO_REMOVED",
                entity_type="BRAND",
                entity_id=str(brand.pk),
                data={"key": previous_key},
            )
    _delete_stored_logo(previous_key)
    return _brand_payload(brand), 200
