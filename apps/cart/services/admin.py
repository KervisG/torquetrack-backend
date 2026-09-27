"""Carritos en el panel: listado, estado, contadores del dashboard y purga."""
from collections import Counter
from datetime import timedelta

from django.db.models import Q
from django.db.models.fields.json import KT
from django.utils import timezone

from apps.cart.models import Cart

# Un carrito en etapa CART sin cambios por más de esta ventana es abandonado.
CART_IDLE_WINDOW = timedelta(minutes=30)

# `items @> '[]'` solo es verdadero para un array: descarta los `items` que no
# son array y el segundo término descarta el array vacío. `_EMPTY_ITEMS` no es
# `~_HAS_ITEMS` porque con `items` ausente la comparación da NULL y la negación
# no lo incluiría.
_HAS_ITEMS = Q(data__items__contains=[]) & ~Q(data__items=[])
_EMPTY_ITEMS = Q(data__items__isnull=True) | ~Q(data__items__contains=[]) | Q(data__items=[])


def classify_cart(stage, updated_at, now) -> str:
    """Única regla de estado de un carrito; la usan el listado del panel y los
    contadores del dashboard para que nunca discrepen."""
    stage = str(stage or "CART").upper()
    if stage != "CART":
        return stage
    return "ACTIVE" if now - updated_at <= CART_IDLE_WINDOW else "ABANDONED"


def _listed_carts():
    return Cart.objects.filter(_HAS_ITEMS)


def list_admin_carts() -> list[dict]:
    """Solo lectura: los carritos vacíos se omiten y se borran con
    `manage.py purge_carts`."""
    now = timezone.now()
    rows = []
    for cart in _listed_carts().order_by("-updated_at"):
        data = cart.data or {}
        status = classify_cart(data.get("stage"), cart.updated_at, now)
        rows.append({**data, "id": cart.pk, "status": status, "updatedAt": cart.updated_at})
    return rows


def count_carts_by_status() -> Counter:
    now = timezone.now()
    pairs = _listed_carts().annotate(stage=KT("data__stage")).values_list("stage", "updated_at")
    return Counter(classify_cart(stage, updated_at, now) for stage, updated_at in pairs)


def purge_empty_carts() -> int:
    deleted, _ = Cart.objects.filter(_EMPTY_ITEMS).delete()
    return deleted
