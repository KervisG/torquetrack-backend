import uuid

from django.db.models import Q
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
    """`items @> '[]'` solo es verdadero para un array, así que su negación
    cubre los `items` que no son array."""
    Cart.objects.filter(
        Q(data__items__isnull=True) | ~Q(data__items__contains=[]) | Q(data__items=[])
    ).delete()


def list_admin_carts() -> list[dict]:
    """Borra primero los carritos vacíos."""
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
