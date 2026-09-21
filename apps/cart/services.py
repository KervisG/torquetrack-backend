"""Business rules for `cart/sync` (task 5.1), ported from
`app/api/cart/sync/route.ts`.

Upsert-by-client-UUID, delete-on-empty. The client UUID (`cartId`) is
generated server-side with `uuid4` when absent, mirroring the legacy
route's `crypto.randomUUID()`.
"""
import uuid

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
