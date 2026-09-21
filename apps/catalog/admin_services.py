"""`admin/products/[id]` business rules (task 7.3), near-verbatim ports of
`app/api/admin/products/[id]/route.ts`'s `PUT`/`DELETE` handlers.

Task 7.3 literally names only `admin/products/[id]` — the collection
`admin/products` (GET/POST, `app/api/admin/products/route.ts`) is NOT
implemented here; it is not claimed by this task's wording and is flagged
as a new scope gap in apply-progress (same precedent as Phase 6's task 7.6
flag for admin quotes list/create).
"""
from __future__ import annotations

from django.utils import timezone

from apps.catalog.models import Product


def upsert_admin_product(product_id: str, payload: dict) -> dict:
    """`PUT /api/admin/products/[id]` — the URL `id` always wins over any
    `id` submitted in the body (`p.id=id` in the legacy route)."""
    product_data = payload.get("product") if isinstance(payload.get("product"), dict) else payload
    product_data = {**product_data, "id": product_id}

    Product.objects.update_or_create(
        id=product_id,
        defaults={"data": product_data, "active": True, "updated_at": timezone.now()},
    )
    return {"ok": True, "product": product_data}


def deactivate_admin_product(product_id: str) -> dict:
    """`DELETE /api/admin/products/[id]` — soft delete (`active=false`).
    A non-existent id is a silent no-op in the legacy `UPDATE`; still
    returns `{ok: true}`, preserved verbatim (no 404 branch)."""
    Product.objects.filter(pk=product_id).update(active=False, updated_at=timezone.now())
    return {"ok": True}
