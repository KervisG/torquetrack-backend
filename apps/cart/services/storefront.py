"""Carrito del storefront: la sincronización desde la sesión del cliente."""
import uuid

from django.utils import timezone

from apps.cart.models import Cart

# El carrito es de la sesión y no del body: quien no tiene la cookie no puede
# tocarlo aunque conozca su id. `login()` conserva los datos de la sesión al
# rotar la key, así que el carrito sobrevive al entrar.
CART_SESSION_KEY = "cart_id"


def sync_cart(session, payload: dict) -> dict:
    """El id sale de la sesión; un `cartId` del body se ignora."""
    stage = str(payload.get("stage") or "CART").upper()
    status = "ACTIVE" if stage == "CART" else stage
    cart_id = session.get(CART_SESSION_KEY)

    items = payload.get("items")
    items = items if isinstance(items, list) else []

    if not items:
        if cart_id:
            Cart.objects.filter(pk=cart_id).delete()
        return {"ok": True, "cartId": cart_id, "status": "EMPTY", "removed": True}

    if not cart_id:
        cart_id = str(uuid.uuid4())
        session[CART_SESSION_KEY] = cart_id

    data = {**payload, "cartId": cart_id, "stage": stage, "status": status}
    Cart.objects.update_or_create(
        id=cart_id,
        defaults={"data": data, "updated_at": timezone.now()},
    )
    return {"ok": True, "cartId": cart_id, "status": status}
