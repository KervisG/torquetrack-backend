from __future__ import annotations

from django.utils import timezone

from apps.catalog.models import Product


def upsert_admin_product(product_id: str, payload: dict) -> dict:
    """El `id` de la URL gana sobre cualquier `id` del body."""
    product_data = payload.get("product") if isinstance(payload.get("product"), dict) else payload
    product_data = {**product_data, "id": product_id}

    Product.objects.update_or_create(
        id=product_id,
        defaults={"data": product_data, "active": True, "updated_at": timezone.now()},
    )
    return {"ok": True, "product": product_data}


def deactivate_admin_product(product_id: str) -> dict:
    Product.objects.filter(pk=product_id).update(active=False, updated_at=timezone.now())
    return {"ok": True}
