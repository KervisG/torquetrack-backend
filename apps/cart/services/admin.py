"""Carritos en el panel: listado, estado, contadores del dashboard y purga."""
from collections import Counter
from datetime import timedelta

from django.db.models import Q, TextField, Value
from django.db.models.fields.json import KT
from django.db.models.functions import Coalesce, NullIf, Upper
from django.utils import timezone

from apps.cart.models import Cart, CartStage, CartStatus

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
    stage = str(stage or CartStage.CART).upper()
    if stage != CartStage.CART:
        return stage
    return CartStatus.ACTIVE if now - updated_at <= CART_IDLE_WINDOW else CartStatus.ABANDONED


# La etapa de `classify_cart` en SQL: ausente, nula o vacía cuenta como CART.
_CART_STAGE = Upper(
    Coalesce(
        NullIf(KT("data__stage"), Value("", output_field=TextField())),
        Value(CartStage.CART, output_field=TextField()),
    )
)


def _listed_carts():
    return Cart.objects.filter(_HAS_ITEMS)


def abandoned_carts(now=None):
    """Carritos ABANDONED según `classify_cart`, resuelto en la base: con
    items, en etapa CART y sin cambios por más de `CART_IDLE_WINDOW`. Lo usan
    el embudo del dashboard y el correo de recuperación."""
    now = now or timezone.now()
    return (
        _listed_carts()
        .annotate(cart_stage=_CART_STAGE)
        .filter(cart_stage=CartStage.CART, updated_at__lt=now - CART_IDLE_WINDOW)
    )


def count_carts_created_between(start, end) -> int:
    """Carritos creados en [start, end) que siguen existiendo: un carrito que
    se vació se borró y ya no cuenta."""
    return Cart.objects.filter(created_at__gte=start, created_at__lt=end).count()


def count_abandoned_carts_between(start, end) -> int:
    """Carritos abandonados hoy cuya última actividad cae en [start, end)."""
    return abandoned_carts().filter(updated_at__gte=start, updated_at__lt=end).count()


def list_admin_carts() -> list[dict]:
    """Solo lectura: los carritos vacíos se omiten y se borran con
    `manage.py purge_carts`."""
    now = timezone.now()
    rows = []
    for cart in _listed_carts().select_related("user").order_by("-updated_at"):
        data = cart.data or {}
        status = classify_cart(data.get("stage"), cart.updated_at, now)
        row = {**data, "id": cart.pk, "status": status, "updatedAt": cart.updated_at}
        # El carrito de una cuenta muestra su email para contactar al cliente.
        if cart.user is not None:
            row["email"] = cart.user.email
        rows.append(row)
    return rows


def count_carts_by_status() -> Counter:
    now = timezone.now()
    pairs = _listed_carts().annotate(stage=KT("data__stage")).values_list("stage", "updated_at")
    return Counter(classify_cart(stage, updated_at, now) for stage, updated_at in pairs)


def purge_empty_carts() -> int:
    deleted, _ = Cart.objects.filter(_EMPTY_ITEMS).delete()
    return deleted
