"""Business rules for `cart/sync` (task 5.1) and `admin/carts` (task 7.3),
ported from `app/api/cart/sync/route.ts` and `app/api/admin/carts/
route.ts`.

Upsert-by-client-UUID, delete-on-empty. The client UUID (`cartId`) is
generated server-side with `uuid4` when absent, mirroring the legacy
route's `crypto.randomUUID()`.
"""
import uuid

from django.db import connection
from django.utils import timezone

from apps.cart.models import Cart


def sync_cart(payload: dict) -> dict:
    cart_id = str(payload.get("cartId") or uuid.uuid4())
    stage = str(payload.get("stage") or "CART").upper()
    status = "ACTIVE" if stage == "CART" else stage
    data = {**payload, "cartId": cart_id, "stage": stage, "status": status}

    items = payload.get("items")
    items = items if isinstance(items, list) else []

    if not items:
        Cart.objects.filter(pk=cart_id).delete()
        return {"ok": True, "cartId": cart_id, "status": "EMPTY", "removed": True}

    Cart.objects.update_or_create(
        id=cart_id,
        defaults={"data": data, "updated_at": timezone.now()},
    )
    return {"ok": True, "cartId": cart_id, "status": status}


def _delete_empty_carts() -> None:
    """`delete from carts where coalesce(jsonb_array_length(...),0)=0` —
    raw SQL (same precedent as `apps.checkout.services.next_order_number`)
    to match the exact jsonb-array-or-missing-key semantics verbatim."""
    with connection.cursor() as cursor:
        cursor.execute(
            "delete from carts where coalesce(jsonb_array_length("
            "case when jsonb_typeof(data->'items') = 'array' then data->'items' "
            "else '[]'::jsonb end), 0) = 0"
        )


def list_admin_carts() -> list[dict]:
    """`GET /api/admin/carts` — deletes empty carts first, then derives a
    `status` per row: `stage='CART'` becomes `ACTIVE`/`ABANDONED` based on
    a 30-minute idle window; any other stage is used verbatim."""
    _delete_empty_carts()

    now = timezone.now()
    carts = Cart.objects.order_by("-updated_at")
    rows = []
    for cart in carts:
        data = cart.data or {}
        stage = str(data.get("stage") or "CART").upper()
        if stage == "CART":
            idle = now - cart.updated_at
            status = "ACTIVE" if idle <= timezone.timedelta(minutes=30) else "ABANDONED"
        else:
            status = stage
        rows.append({**data, "id": cart.pk, "status": status, "updatedAt": cart.updated_at})
    return rows
