"""Carrito del storefront: el backend es la fuente de verdad de su contenido.

Con una cuenta autenticada el carrito es el de la cuenta (`Cart.user`) y se lee
igual desde cualquier dispositivo; un invitado usa el carrito de su sesión. Los
items guardados son `[{id, qty, title, partNumber, priceAtAdd}]`: el título y
el número de parte son una foto del catálogo para el panel, y cada lectura
reprecia con `price_lines`.

`priceAtAdd` no es un precio de venta: es la referencia para avisar que el
precio cambió desde que el producto entró al carrito (como Amazon). La fija el
servidor con el precio del catálogo de ese momento y nunca sale del body. Un
`PUT` conserva la referencia de los productos que ya estaban y solo la mueve
al precio actual si trae `acknowledgePrices: true`, la marca que manda el SPA
después de mostrar el aviso. Así un guardado automático, otro dispositivo o
una respuesta que el SPA descartó no hacen desaparecer un aviso que nadie vio.
El cobro nunca lee la referencia: el checkout reprecia con el catálogo.
"""
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.cart.models import Cart, CartStage
from apps.catalog.services.pricing import (
    MAX_STOREFRONT_QUANTITY,
    STOREFRONT_QUANTITY_ERROR,
    UnpricedProducts,
    parse_quantity,
    price_lines,
)
from apps.common.numbers import ZERO, money, money_decimal

# El carrito invitado es de la sesión y no del body: quien no tiene la cookie
# no puede tocarlo aunque conozca su id. Al iniciar sesión se fusiona con el de
# la cuenta y la clave sale de la sesión.
CART_SESSION_KEY = "cart_id"

# Acota el JSON que un cliente puede guardar; un carrito real no se acerca.
MAX_CART_LINES = 100

CART_ITEMS_ERROR = "Items must be a list of objects with an id and qty"
DUPLICATE_ITEM_ERROR = "Each product can appear only once in the cart"
TOO_MANY_LINES_ERROR = f"A cart can hold at most {MAX_CART_LINES} different products"

PRICE_REFERENCE_KEY = "priceAtAdd"


def _is_signed_in(user) -> bool:
    return bool(user is not None and user.is_authenticated)


def _cart_queryset(user, session, *, lock: bool):
    carts = Cart.objects.select_for_update() if lock else Cart.objects
    if _is_signed_in(user):
        return carts.filter(user=user)
    cart_id = session.get(CART_SESSION_KEY)
    if not cart_id:
        return carts.none()
    # Una sesión anónima nunca alcanza un carrito con dueño, aunque su
    # `cart_id` apunte a uno.
    return carts.filter(pk=cart_id, user__isnull=True)


def _lock_user(user) -> None:
    """Serializa las escrituras del carrito de una cuenta: dos requests (o dos
    logins) simultáneos no pueden crear dos carritos ni sumar dos veces."""
    list(get_user_model().objects.select_for_update(of=("self",)).filter(pk=user.pk))


def current_cart_id(user, session) -> str | None:
    """Id del carrito que el checkout y la cotización marcan como usado. Para
    un invitado es el de la sesión aunque la fila ya no exista (como antes)."""
    if _is_signed_in(user):
        return Cart.objects.filter(user=user).values_list("pk", flat=True).first()
    return session.get(CART_SESSION_KEY)


def _stored_items(data) -> list[dict]:
    """Items guardados que siguen bien formados; lo demás se ignora."""
    items = (data or {}).get("items")
    rows = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        qty = parse_quantity(item.get("qty"))
        if qty is not None:
            rows.append({"id": item["id"], "qty": qty})
    return rows


def _price(items: list[dict]) -> tuple[list[dict], dict, list[str], dict]:
    """Reprecia con el catálogo. Devuelve las líneas en el orden del carrito,
    los totales, los ids que no son productos activos y el precio unitario
    actual (`Decimal`) de cada producto con precio. Un producto sin precio
    válido se lista con precio `None` y queda fuera del subtotal: el checkout
    es quien lo rechaza."""
    try:
        priced = price_lines(items)
        unpriced = []
    except UnpricedProducts as exc:
        unpriced = exc.lines
        unpriced_ids = {line.item["id"] for line in unpriced}
        priced = price_lines([item for item in items if item["id"] not in unpriced_ids])

    by_id = {line.item["id"]: line for line in [*priced.lines, *unpriced]}
    rows, missing, current = [], [], {}
    for item in items:
        line = by_id.get(item["id"])
        if line is None:
            missing.append(item["id"])
            continue
        product = line.product
        sellable = line.unit_price > 0
        if sellable:
            current[item["id"]] = money_decimal(line.unit_price)
        rows.append(
            {
                "id": item["id"],
                "qty": line.quantity,
                "title": product.get("title") or product.get("partNumber") or item["id"],
                "partNumber": (
                    product.get("partNumber")
                    or product.get("oemPart")
                    or product.get("aftermarketPart")
                    or ""
                ),
                "price": money(line.unit_price) if sellable else None,
                "coreCharge": money(line.core_charge) if sellable else None,
                "lineTotal": money(line.line_total) if sellable else None,
            }
        )
    totals = {"subtotal": money(priced.subtotal), "core": money(priced.core)}
    return rows, totals, missing, current


def _stored_references(data) -> dict:
    """`priceAtAdd` guardado de cada producto, en `Decimal`. Una referencia
    ausente o que no es número (carritos anteriores al aviso) no cuenta."""
    items = (data or {}).get("items")
    references = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        value = item.get(PRICE_REFERENCE_KEY)
        if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
            references[item["id"]] = money_decimal(value)
    return references


def _format_amount(value) -> str:
    return f"${value:,.2f}"


def _mark_price_changes(rows: list[dict], current: dict, references: dict) -> list[str]:
    """Marca cada línea con `priceChanged` (y `previousPrice` si cambió) y
    devuelve los avisos. Una línea sin precio válido o sin referencia no avisa:
    no hay dos montos que comparar."""
    notices = []
    for row in rows:
        now, before = current.get(row["id"]), references.get(row["id"])
        changed = now is not None and before is not None and now != before
        row["priceChanged"] = changed
        if changed:
            row["previousPrice"] = money(before)
            notices.append(
                f"The price of {row['title']} has changed from "
                f"{_format_amount(before)} to {_format_amount(now)}."
            )
    return notices


def _cart_body(rows: list[dict], totals: dict, current: dict, references: dict) -> dict:
    notices = _mark_price_changes(rows, current, references)
    return {"items": rows, **totals, "notices": notices}


def _empty_body() -> dict:
    return {"items": [], "subtotal": money(ZERO), "core": money(ZERO), "notices": []}


def _snapshot(rows: list[dict], references: dict) -> list[dict]:
    items = []
    for row in rows:
        item = {
            "id": row["id"],
            "qty": row["qty"],
            "title": row["title"],
            "partNumber": row["partNumber"],
        }
        if row["id"] in references:
            item[PRICE_REFERENCE_KEY] = money(references[row["id"]])
        items.append(item)
    return items


def _write(cart: Cart, rows: list[dict], references: dict) -> None:
    # Todo cambio de contenido devuelve el carrito a la etapa CART y descarta
    # el vínculo con un pedido o una cotización anteriores.
    cart.data = {"items": _snapshot(rows, references), "stage": CartStage.CART}
    cart.updated_at = timezone.now()
    cart.save()


def _backfill_references(cart: Cart, current: dict) -> dict:
    """Un carrito anterior al aviso toma el precio actual como referencia la
    primera vez que se lee, sin avisar. Solo agrega `priceAtAdd` a los items
    que no lo tienen: no toca la etapa, los productos desactivados ni
    `updated_at` (guardar la referencia no es actividad del cliente y el
    panel no debe verlo como un carrito activo)."""
    references = _stored_references(cart.data)
    if all(product_id in references for product_id in current):
        return references
    with transaction.atomic():
        # Relee bloqueando: un `PUT` simultáneo no pierde su escritura.
        locked = Cart.objects.select_for_update().filter(pk=cart.pk).first()
        if locked is None:
            return references
        data = dict(locked.data or {})
        references = _stored_references(data)
        items = data.get("items") if isinstance(data.get("items"), list) else []
        changed = False
        for item in items:
            if not isinstance(item, dict):
                continue
            product_id = item.get("id")
            if product_id in current and product_id not in references:
                item[PRICE_REFERENCE_KEY] = money(current[product_id])
                references[product_id] = current[product_id]
                changed = True
        if changed:
            Cart.objects.filter(pk=locked.pk).update(data=data)
    return references


def get_cart(user, session) -> dict:
    """Un producto desactivado se omite sin reescribir la fila; la única
    escritura es la referencia de precio de un carrito viejo."""
    cart = _cart_queryset(user, session, lock=False).first()
    if cart is None:
        return _empty_body()
    rows, totals, _, current = _price(_stored_items(cart.data))
    references = _backfill_references(cart, current)
    return _cart_body(rows, totals, current, references)


def _parse_items(raw) -> list[dict] | dict:
    """Items `[{id, qty}]` limpios, o el dict de error."""
    if not isinstance(raw, list) or not all(
        isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
        for item in raw
    ):
        return {"error": CART_ITEMS_ERROR, "status": 400}
    if len(raw) > MAX_CART_LINES:
        return {"error": TOO_MANY_LINES_ERROR, "status": 400}
    items = []
    for item in raw:
        # A diferencia del checkout, una cantidad ausente no vale 1: el
        # carrito guarda exactamente lo que el cliente eligió.
        qty = item.get("qty")
        qty = None if qty is None else parse_quantity(qty, max_quantity=MAX_STOREFRONT_QUANTITY)
        if qty is None:
            return {"error": STOREFRONT_QUANTITY_ERROR, "status": 400}
        items.append({"id": item["id"].strip(), "qty": qty})
    if len({item["id"] for item in items}) != len(items):
        return {"error": DUPLICATE_ITEM_ERROR, "status": 400}
    return items


def _put_references(rows: list[dict], current: dict, stored: dict, acknowledge: bool) -> dict:
    """Referencia de cada línea tras un `PUT`: un producto nuevo (o uno de un
    carrito viejo sin referencia) toma el precio actual; uno que ya estaba
    conserva la suya salvo que el cliente acepte el aviso. Un producto sin
    precio válido nunca recibe referencia nueva."""
    references = {}
    for row in rows:
        product_id = row["id"]
        if product_id in stored and not (acknowledge and product_id in current):
            references[product_id] = stored[product_id]
        elif product_id in current:
            references[product_id] = current[product_id]
    return references


def replace_cart(user, session, payload: dict) -> dict:
    """Reemplaza todos los items. El id sale de la cuenta o de la sesión; un
    `cartId` del body se ignora. Un `items` vacío borra el carrito. Solo
    `acknowledgePrices: true` (el booleano) acepta los avisos de precio."""
    items = _parse_items(payload.get("items"))
    if isinstance(items, dict):
        return items
    acknowledge = payload.get("acknowledgePrices") is True
    rows, totals, missing, current = _price(items)
    if missing:
        return {"error": f"These products are not available: {', '.join(missing)}", "status": 400}

    signed_in = _is_signed_in(user)
    with transaction.atomic():
        if signed_in:
            _lock_user(user)
        cart = _cart_queryset(user, session, lock=True).first()
        if not rows:
            if cart is not None:
                cart.delete()
            return _empty_body()
        stored = _stored_references(cart.data) if cart is not None else {}
        if cart is None:
            cart = Cart(id=str(uuid.uuid4()), user=user if signed_in else None)
            if not signed_in:
                session[CART_SESSION_KEY] = cart.pk
        references = _put_references(rows, current, stored, acknowledge)
        _write(cart, rows, references)
    return _cart_body(rows, totals, current, references)


def _merge_items(account: list[dict], guest: list[dict]) -> list[dict]:
    """Suma el mismo producto con tope 99 y agrega los distintos al final."""
    merged = {item["id"]: item["qty"] for item in account}
    for item in guest:
        merged[item["id"]] = min(MAX_STOREFRONT_QUANTITY, merged.get(item["id"], 0) + item["qty"])
    return [{"id": product_id, "qty": qty} for product_id, qty in merged.items()]


def merge_session_cart(user, session) -> None:
    """Fusiona el carrito invitado de la sesión con el de la cuenta y lo
    consume. Idempotente: con el usuario bloqueado, una segunda fusión ya no
    encuentra el carrito invitado (se borró o pasó a tener dueño).

    Referencia de precio: la del carrito de la cuenta si la tiene, si no la
    del invitado (el producto entró al carrito ahí) y, sin ninguna, el precio
    actual. Así el aviso compara contra el precio que el cliente vio primero
    en la cuenta."""
    cart_id = session.pop(CART_SESSION_KEY, None)
    if not cart_id:
        return
    with transaction.atomic():
        _lock_user(user)
        guest = (
            Cart.objects.select_for_update().filter(pk=cart_id, user__isnull=True).first()
        )
        if guest is None:
            return
        account = Cart.objects.select_for_update().filter(user=user).first()
        if account is None:
            guest.user = user
            guest.updated_at = timezone.now()
            guest.save(update_fields=["user", "updated_at"])
            return
        merged = _merge_items(_stored_items(account.data), _stored_items(guest.data))
        rows, _, _, current = _price(merged)
        stored = {**_stored_references(guest.data), **_stored_references(account.data)}
        references = _put_references(rows, current, stored, acknowledge=False)
        guest.delete()
        if rows:
            _write(account, rows, references)
        else:
            account.delete()
