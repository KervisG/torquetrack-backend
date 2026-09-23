from __future__ import annotations

from django.utils import timezone

from apps.catalog.models import Product

PRICE_FIELDS = ("price", "compareAt", "coreCharge")
# Deben seguir incluidos en `RESTRICTED_PRODUCT_FIELDS` de `serializers.py`.
COST_FIELDS = ("purchaseCost", "supplierCost")
PROTECTED_FIELDS = PRICE_FIELDS + COST_FIELDS


def serialize_admin_product(data: dict, *, can_view_costs: bool) -> dict:
    if can_view_costs:
        return dict(data)
    return {key: value for key, value in data.items() if key not in COST_FIELDS}


def upsert_admin_product(
    product_id: str, payload: dict, *, can_edit_pricing: bool, can_view_costs: bool
) -> tuple[dict, int]:
    """El `id` de la URL gana sobre cualquier `id` del body.

    El PUT reemplaza `data`, salvo los campos de precio y costo ausentes, que
    conservan su valor: quien no ve los costos no puede reenviarlos y no debe
    borrarlos. `active` cambia solo si viene en el body.
    """
    raw = payload.get("product") if isinstance(payload.get("product"), dict) else payload
    product_data = {key: value for key, value in raw.items() if key != "active"}
    product_data["id"] = product_id

    active = payload["active"] if "active" in payload else raw.get("active")
    if active is not None and not isinstance(active, bool):
        return {"error": "active must be a boolean"}, 400

    product = Product.objects.filter(pk=product_id).first()
    stored = (product.data or {}) if product is not None else {}
    for field in PROTECTED_FIELDS:
        if field not in product_data and field in stored:
            product_data[field] = stored[field]

    changed = [f for f in PROTECTED_FIELDS if product_data.get(f) != stored.get(f)]
    if changed and not can_edit_pricing:
        return {"error": "Changing prices or costs requires pricing.edit"}, 403

    if product is None:
        product = Product(id=product_id, active=True if active is None else active)
    elif active is not None:
        product.active = active
    product.data = product_data
    product.updated_at = timezone.now()
    product.save()

    return {
        "ok": True,
        "product": serialize_admin_product(product_data, can_view_costs=can_view_costs),
    }, 200


def deactivate_admin_product(product_id: str) -> tuple[dict, int]:
    updated = Product.objects.filter(pk=product_id).update(
        active=False, updated_at=timezone.now()
    )
    if not updated:
        return {"error": "Product not found"}, 404
    return {"ok": True}, 200
