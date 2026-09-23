"""Compatibilidad entre producto y vehículo. Solo `check_cart_fitment` lee la
base; el resto no hace I/O. Los mensajes de
`reasons`/`warnings` muestran los valores tal como los escribió el catálogo o
el decodificador, sin normalizar."""
import re

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _text(value) -> str:
    return str(value if value is not None else "").strip().lower()


def _num(value):
    """Primer número del texto (`"6.7L Power Stroke"` -> 6.7), o `None`."""
    match = _NUMBER_RE.search(str(value if value is not None else ""))
    return float(match.group(0)) if match else None


def _js_number_or(raw, fallback=0):
    """`None`, `False`, `""` y `0` usan `fallback`, igual que un texto que no es número."""
    if raw in (None, False, "", 0, 0.0):
        return fallback
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def _fmt(number) -> str:
    """Los enteros se muestran sin `.0` (`2010`, no `2010.0`)."""
    if number == int(number):
        return str(int(number))
    return str(number)


def _make_matches(product_make, vehicle_make) -> bool:
    product_text = _text(product_make)
    vehicle_text = _text(vehicle_make)
    if not product_text or not vehicle_text:
        return True
    if "chevrolet / gmc" in product_text or "chevrolet/gmc" in product_text:
        return "chevrolet" in vehicle_text or "gmc" in vehicle_text
    if product_text == "ram":
        return "ram" in vehicle_text or "dodge" in vehicle_text
    return vehicle_text in product_text or product_text in vehicle_text


def check_product_fitment(product: dict | None, vehicle: dict | None) -> dict:
    product = product or {}
    vehicle = vehicle or {}
    reasons: list[str] = []
    warnings: list[str] = []

    year = _js_number_or(vehicle.get("year"), 0)
    year_from = _js_number_or(product.get("yearFrom"), 0)
    year_to = _js_number_or(product.get("yearTo"), year_from)
    if year and year_from and year_to and (year < year_from or year > year_to):
        reasons.append(f"year {_fmt(year)} is outside {_fmt(year_from)}-{_fmt(year_to)}")

    if not _make_matches(product.get("make"), vehicle.get("make")):
        vehicle_make = vehicle.get("make") or "unknown"
        product_make = product.get("make") or "product application"
        reasons.append(f"vehicle make {vehicle_make} does not match {product_make}")

    product_engine = product.get("engineFamily") or product.get("engine")
    vehicle_engine = vehicle.get("engine")
    product_engine_num = _num(product_engine)
    vehicle_engine_num = _num(vehicle_engine)
    engine_mismatch = (
        product_engine_num
        and vehicle_engine_num
        and abs(product_engine_num - vehicle_engine_num) > 0.15
    )
    if engine_mismatch:
        reasons.append(f"engine {vehicle_engine} does not match required {product_engine}")
    if product_engine_num and not vehicle_engine_num:
        warnings.append(
            f"VIN decoder did not return engine displacement; "
            f"verify {product_engine} manually before ordering"
        )

    return {"compatible": len(reasons) == 0, "reasons": reasons, "warnings": warnings}


def _item_id(item) -> str:
    if isinstance(item, dict):
        return str(item.get("id") or item.get("productId") or "").strip()
    return ""


def check_cart_fitment(items, vehicle) -> tuple[dict, int]:
    """Un id inexistente o inactivo cuenta como incompatible: si se omitiera,
    un carrito sin productos válidos daría `compatible: True`."""
    from apps.catalog.models import Product

    if not isinstance(items, list) or not items:
        return {"error": "Cart is empty"}, 400
    ids = [_item_id(item) for item in items]
    if not all(ids):
        return {"error": "Each cart item must have a product id"}, 400

    products = {p.pk: p for p in Product.objects.filter(id__in=ids, active=True)}
    results = []
    for product_id in dict.fromkeys(ids):
        product = products.get(product_id)
        if product is None:
            results.append(
                {
                    "id": product_id,
                    "title": "",
                    "partNumber": "",
                    "compatible": False,
                    "reasons": ["product is not available"],
                    "warnings": [],
                }
            )
            continue
        data = product.data or {}
        results.append(
            {
                "id": product.pk,
                "title": data.get("title"),
                "partNumber": data.get("partNumber")
                or data.get("oemPart")
                or data.get("aftermarketPart")
                or "",
                **check_product_fitment(data, vehicle),
            }
        )

    compatible = all(result["compatible"] for result in results)
    return {"compatible": compatible, "results": results}, 200
