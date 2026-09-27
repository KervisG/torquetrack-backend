"""Las tarifas que ve el cliente se recuerdan para que el checkout cobre el
monto cotizado y no el que manda el navegador."""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache

from apps.catalog.models import Product
from apps.common.numbers import money, to_number
from apps.integrations.exceptions import ProviderError
from apps.integrations.shipping import easypost

logger = logging.getLogger(__name__)

OUNCES_PER_POUND = 16
# Una tarifa cotizada solo vale para pagar durante este lapso; después el
# cliente vuelve a pedir tarifas y el checkout cobra el precio vigente.
SHIPPING_QUOTE_TTL_SECONDS = 60 * 60
# El detalle de EasyPost puede nombrar la cuenta o la key: va al log, no al cliente.
RATES_UNAVAILABLE = "Shipping rates are temporarily unavailable. Please try again."


def _quote_cache_key(shipment_id: str) -> str:
    return f"shipping:quote:{shipment_id}"


def _zip5(value) -> str:
    return str(value or "").strip()[:5]


def _norm_rate(rate: dict | None, shipment_id: str) -> dict | None:
    if not rate:
        return None
    return {
        "id": rate["id"],
        "shipmentId": shipment_id,
        "carrier": rate["carrier"],
        "service": rate["service"],
        "rate": rate["rate"],
        "deliveryDays": rate["delivery_days"],
        "guaranteed": rate["guaranteed"],
    }


# Caja por defecto (pulgadas) y peso por unidad (libras) cuando el catálogo
# no trae el dato.
DEFAULT_BOX = {"length": 12, "width": 10, "height": 6}
DEFAULT_WEIGHT_LB = 1
MAX_ITEM_QTY = 99


def normalize_items(raw_items) -> dict[str, int] | None:
    """`{product_id: qty}`, o `None` si algún ítem no es válido. La cantidad se
    acota igual que en el checkout y los ids repetidos se suman."""
    if not isinstance(raw_items, list) or not raw_items:
        return None
    quantities: dict[str, int] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, dict) or not raw_item.get("id"):
            return None
        qty = max(1, min(MAX_ITEM_QTY, int(to_number(raw_item.get("qty"), 1))))
        product_id = str(raw_item["id"])
        quantities[product_id] = min(MAX_ITEM_QTY, quantities.get(product_id, 0) + qty)
    return quantities


def _unit_weight_oz(product_id: str, data: dict) -> float:
    """`shippingWeight` está en libras y `weightOz` en onzas. Sin ninguno se
    registra el faltante para completar el catálogo."""
    pounds = to_number(data.get("shippingWeight"), 0)
    if pounds > 0:
        return pounds * OUNCES_PER_POUND
    ounces = to_number(data.get("weightOz"), 0)
    if ounces > 0:
        return ounces
    logger.warning("Product %s has no shipping weight; using %s lb", product_id, DEFAULT_WEIGHT_LB)
    return DEFAULT_WEIGHT_LB * OUNCES_PER_POUND


def _dimension(data: dict, keys: tuple[str, str], default: float) -> float:
    value = to_number(data.get(keys[0]) or data.get(keys[1]), 0)
    return value if value > 0 else default


def _items_parcel(quantities: dict[str, int]) -> tuple[dict | None, str | None]:
    """Paquete en onzas y pulgadas con las unidades apiladas en una sola caja,
    o `(None, id)` con el primer producto inexistente o inactivo."""
    products = {
        product.id: product.data or {}
        for product in Product.objects.filter(id__in=list(quantities), active=True)
    }
    missing = next((product_id for product_id in quantities if product_id not in products), None)
    if missing is not None:
        return None, missing

    weight = length = width = height = 0.0
    for product_id, qty in quantities.items():
        data = products[product_id]
        weight += _unit_weight_oz(product_id, data) * qty
        length = max(length, _dimension(data, ("packageLength", "lengthIn"), DEFAULT_BOX["length"]))
        width = max(width, _dimension(data, ("packageWidth", "widthIn"), DEFAULT_BOX["width"]))
        height += _dimension(data, ("packageHeight", "heightIn"), DEFAULT_BOX["height"]) * qty
    parcel = {
        "weight": max(weight, OUNCES_PER_POUND),
        "length": length,
        "width": width,
        "height": height,
    }
    return parcel, None


def get_shipping_rates(payload: dict) -> tuple[dict, int]:
    """El paquete lo arma el servidor desde el catálogo; un `parcel` del body
    se ignora, porque un paquete más liviano cotizaría un envío más barato.
    Cada tarifa lleva su `id` y su `shipmentId`, que es lo que el checkout
    manda para cobrarla.
    """
    if not easypost.is_configured():
        return (
            {
                "configured": False,
                "message": (
                    "EasyPost is not configured. Add EASYPOST_API_KEY to the server environment."
                ),
            },
            200,
        )

    quantities = normalize_items(payload.get("items"))
    if quantities is None:
        return {"error": "Add at least one item to get shipping rates"}, 400
    parcel, missing = _items_parcel(quantities)
    if parcel is None:
        return {"error": f"Product is not available: {missing}"}, 400

    to_address = payload.get("to")
    try:
        shipment = easypost.get_rates(
            to_address=to_address,
            from_address={"zip": settings.SHIP_FROM_ZIP or "34241", "country": "US"},
            parcel=parcel,
        )
    except ProviderError as exc:
        logger.warning("EasyPost rate request failed: %s", exc)
        return {"error": RATES_UNAVAILABLE}, 502

    shipment_id = shipment["shipment_id"]
    rates = sorted(shipment["rates"], key=lambda rate: rate["rate"])

    def pick(test):
        return _norm_rate(
            next((rate for rate in rates if test(str(rate.get("service") or "").lower())), None),
            shipment_id,
        )

    options = {
        "ground": pick(lambda service: "ground" in service),
        "secondDay": pick(
            lambda service: "2day" in service or "2nd" in service or "second" in service
        ),
        "overnight": pick(
            lambda service: "next" in service or "overnight" in service or "priority" in service
        ),
    }
    _remember_quote(
        shipment_id, to_address, quantities, [rate for rate in options.values() if rate]
    )

    return {"configured": True, "shipmentId": shipment_id, **options}, 200


def _remember_quote(shipment_id, to_address, quantities: dict[str, int], rates: list[dict]) -> None:
    """Guarda solo las tarifas que vio el cliente, atadas al ZIP y a los ítems
    cotizados: una tarifa pedida para otro destino u otro paquete no sirve
    para pagar este envío."""
    if not shipment_id or not rates:
        return
    to_zip = _zip5((to_address or {}).get("zip") if isinstance(to_address, dict) else None)
    cache.set(
        _quote_cache_key(shipment_id),
        {
            "zip": to_zip,
            "items": quantities,
            "rates": {
                rate["id"]: {
                    "carrier": rate["carrier"],
                    "service": rate["service"],
                    "rate": rate["rate"],
                }
                for rate in rates
            },
        },
        SHIPPING_QUOTE_TTL_SECONDS,
    )


def verify_shipping_selection(selection, destination_zip, *, items) -> dict | None:
    """`None` si la tarifa no existe, venció o se cotizó para otro ZIP u otros
    ítems. El monto sale del cache, nunca del body."""
    if not isinstance(selection, dict):
        return None
    shipment_id = str(selection.get("shipmentId") or "")
    rate_id = str(selection.get("rateId") or "")
    if not shipment_id or not rate_id or not _zip5(destination_zip):
        return None

    quote = cache.get(_quote_cache_key(shipment_id))
    if not quote or quote.get("zip") != _zip5(destination_zip):
        return None
    # Una tarifa cotizada para un paquete más liviano no paga uno más pesado.
    quoted_items = quote.get("items")
    if not quoted_items or normalize_items(items) != quoted_items:
        return None
    rate = (quote.get("rates") or {}).get(rate_id)
    if rate is None:
        return None
    return {
        "shipmentId": shipment_id,
        "rateId": rate_id,
        "carrier": rate["carrier"],
        "service": rate["service"],
        "rate": money(rate["rate"]),
    }
