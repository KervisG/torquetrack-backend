"""Reglas de negocio de `admin/products/[id]` (`PUT`/`DELETE`).

La colección `admin/products` (GET/POST) todavía no está implementada.
"""
from __future__ import annotations

from django.utils import timezone

from apps.catalog.models import Product


def upsert_admin_product(product_id: str, payload: dict) -> dict:
    """`PUT /api/admin/products/[id]`: el `id` de la URL siempre gana sobre
    cualquier `id` enviado en el body."""
    product_data = payload.get("product") if isinstance(payload.get("product"), dict) else payload
    product_data = {**product_data, "id": product_id}

    Product.objects.update_or_create(
        id=product_id,
        defaults={"data": product_data, "active": True, "updated_at": timezone.now()},
    )
    return {"ok": True, "product": product_data}


def deactivate_admin_product(product_id: str) -> dict:
    """`DELETE /api/admin/products/[id]`: borrado lógico (`active=false`).
    Comportamiento intencional del contrato: un id inexistente no hace nada
    y aun así responde `{ok: true}` (no hay rama 404)."""
    Product.objects.filter(pk=product_id).update(active=False, updated_at=timezone.now())
    return {"ok": True}
