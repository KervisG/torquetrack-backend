"""Compatibilidad entre producto y vehículo. Solo `check_cart_fitment` y
`applications_by_product` leen la base; el resto no hace I/O.

Con filas de `ProductFitment` (las `applications` de un producto) el vehículo
tiene que caer en alguna de ellas; sin filas se compara el texto de `data`
(marca, años y motor) como siempre. Los mensajes de
`reasons`/`warnings` muestran los valores tal como los escribió el catálogo o
el decodificador, sin normalizar."""
import re

from apps.common.numbers import to_number

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _text(value) -> str:
    return str(value if value is not None else "").strip().lower()


def _first_number(value):
    """Primer número del texto (`"6.7L Power Stroke"` -> 6.7), o `None`."""
    match = _NUMBER_RE.search(str(value if value is not None else ""))
    return float(match.group(0)) if match else None


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


def _year_reasons(product: dict, vehicle: dict) -> list[str]:
    year = to_number(vehicle.get("year"), 0)
    year_from = to_number(product.get("yearFrom"), 0)
    year_to = to_number(product.get("yearTo"), year_from)
    if year and year_from and year_to and (year < year_from or year > year_to):
        return [f"year {_fmt(year)} is outside {_fmt(year_from)}-{_fmt(year_to)}"]
    return []


def _engine_matches(required, vehicle_engine) -> bool:
    required_num = _first_number(required)
    vehicle_num = _first_number(vehicle_engine)
    return not (required_num and vehicle_num and abs(required_num - vehicle_num) > 0.15)


def _application_matches(application: dict, vehicle: dict) -> bool:
    """Cada dato del vehículo que venga tiene que coincidir; uno ausente no
    descarta (igual que el chequeo por texto)."""
    year = to_number(vehicle.get("year"), 0)
    year_from = to_number(application.get("yearFrom"), 0)
    year_to = to_number(application.get("yearTo"), year_from)
    if year and year_from and (year < year_from or year > year_to):
        return False
    return _make_matches(application.get("make"), vehicle.get("make")) and _engine_matches(
        application.get("engine"), vehicle.get("engine")
    )


def _describe_vehicle(vehicle: dict) -> str:
    parts = [vehicle.get(key) for key in ("year", "make", "model", "engine")]
    return " ".join(str(part).strip() for part in parts if str(part or "").strip())


def _check_application_fitment(product: dict, vehicle: dict, applications: list[dict]) -> dict:
    reasons = _year_reasons(product, vehicle)
    warnings: list[str] = []

    # El garaje del SPA manda el id exacto de la aplicación elegida.
    application_id = str(vehicle.get("applicationId") or "").strip()
    if application_id:
        if application_id not in {str(app.get("id")) for app in applications}:
            reasons.append(
                f"vehicle application {application_id} is not listed for this product"
            )
    elif _describe_vehicle(vehicle) and not any(
        _application_matches(app, vehicle) for app in applications
    ):
        reasons.append(
            f"vehicle {_describe_vehicle(vehicle)} is not a listed application for this product"
        )

    if not application_id and not _first_number(vehicle.get("engine")):
        engines = list(
            dict.fromkeys(str(app.get("engine")) for app in applications if app.get("engine"))
        )
        if engines and _describe_vehicle(vehicle):
            warnings.append(
                f"VIN decoder did not return engine displacement; "
                f"verify {' / '.join(engines)} manually before ordering"
            )

    return {"compatible": len(reasons) == 0, "reasons": reasons, "warnings": warnings}


def check_product_fitment(
    product: dict | None, vehicle: dict | None, applications: list[dict] | None = None
) -> dict:
    """`applications` son las aplicaciones del producto (`applications_by_product`);
    vacías o `None` = el producto no tiene filas y se usa el texto."""
    product = product or {}
    vehicle = vehicle or {}
    if applications:
        return _check_application_fitment(product, vehicle, applications)

    reasons = _year_reasons(product, vehicle)
    warnings: list[str] = []

    if not _make_matches(product.get("make"), vehicle.get("make")):
        vehicle_make = vehicle.get("make") or "unknown"
        product_make = product.get("make") or "product application"
        reasons.append(f"vehicle make {vehicle_make} does not match {product_make}")

    product_engine = product.get("engineFamily") or product.get("engine")
    vehicle_engine = vehicle.get("engine")
    product_engine_num = _first_number(product_engine)
    vehicle_engine_num = _first_number(vehicle_engine)
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


def applications_by_product(product_ids) -> dict[str, list[dict]]:
    """`{product_id: [aplicación serializada, ...]}` solo para los productos con
    filas; un producto ausente del dict usa el chequeo por texto."""
    from apps.catalog.models import ProductFitment
    from apps.catalog.services import serialize_application

    grouped: dict[str, list[dict]] = {}
    rows = (
        ProductFitment.objects.filter(product_id__in=list(product_ids))
        .select_related("application")
        .order_by("application__code")
    )
    for row in rows:
        grouped.setdefault(row.product_id, []).append(serialize_application(row.application))
    return grouped


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
    fitments = applications_by_product(products)
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
                **check_product_fitment(data, vehicle, fitments.get(product.pk)),
            }
        )

    compatible = all(result["compatible"] for result in results)
    return {"compatible": compatible, "results": results}, 200
