"""Lógica pura de compatibilidad (fitment) entre producto y vehículo.

No tiene I/O. Los mensajes de `reasons`/`warnings` usan a propósito los
valores crudos, sin normalizar, de los campos de producto y vehículo.
"""
import re

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _text(value) -> str:
    """Mirror JS `String(v ?? "").trim().toLowerCase()`."""
    return str(value if value is not None else "").strip().lower()


def _num(value):
    """Mirror JS `num()`: first decimal number found in the string form, or
    `None` (JS `null`) if there isn't one."""
    match = _NUMBER_RE.search(str(value if value is not None else ""))
    return float(match.group(0)) if match else None


def _js_number_or(raw, fallback=0):
    """Mirror JS `Number(raw || fallback)`: falsy `raw` (None/0/""/False)
    uses `fallback`; otherwise coerce `raw` to a number."""
    if raw in (None, False, "", 0, 0.0):
        return fallback
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def _fmt(number) -> str:
    """Render a computed number the way a JS template literal would:
    whole numbers with no trailing `.0`."""
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
