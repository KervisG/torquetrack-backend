"""Búsqueda, filtros y paginación del catálogo de la tienda.

El servidor devuelve una página y las opciones de los filtros (`facets`); el
SPA ya no baja el catálogo entero para filtrarlo. Las reglas son las que
tenía `filter-products.ts` del SPA y sus mensajes viven allá.
"""

from __future__ import annotations

import math
import re

from django.db.models import (
    DecimalField,
    Exists,
    F,
    Func,
    Max,
    OuterRef,
    Q,
    TextField,
    Value,
)
from django.db.models.fields.json import KT
from django.db.models.functions import Coalesce, Concat, Lower

from apps.catalog.models import Application, Product, ProductFitment
from apps.catalog.services.fitment import _displacement, _makes
from apps.common.numbers import to_number

DEFAULT_PAGE_SIZE = 16
MAX_PAGE_SIZE = 100

# Mismos alias que `canonicalCategory` del SPA: el filtro manda la categoría
# canónica y acá se cruza con el texto guardado en cada producto.
_CATEGORY_ALIASES = {
    "TURBOCHARGER": "TURBO",
    "TURBOCHARGERS": "TURBO",
    "INJECTORS": "INJECTOR",
    "FUEL INJECTOR": "INJECTOR",
    "FUEL INJECTORS": "INJECTOR",
    "HIGH PRESSURE FUEL PUMP": "HPFP",
    "HIGH PRESSURE FUEL PUMPS": "HPFP",
    "CONTAMINATION KITS": "CONTAMINATION KIT",
    "TURBO ACTUATORS": "TURBO ACTUATOR",
    "FUEL RAILS": "FUEL RAIL",
}
_NOT_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")
# Columnas y claves de `attributes` donde busca el texto libre.
_TEXT_COLUMNS = ("title", "category", "make", "model", "manufacturer", "part_number")
_TEXT_ATTRIBUTES = (
    "type",
    "oemPart",
    "aftermarketPart",
    "remanPart",
    "fitment",
    "engine",
    "engineFamily",
    "engineCode",
)
_PART_NUMBER_ATTRIBUTES = ("oemPart", "aftermarketPart", "remanPart")
_SERIES = re.compile(r"(?:F[- ]?)(250|350|450|550)|\b(2500|3500|4500|5500)\b")
_VEHICLE_PARAMS = ("applicationId", "vehicleYear", "vehicleMake", "vehicleModel", "vehicleEngine")
_MONEY = DecimalField(max_digits=12, decimal_places=2)
_TEXT = TextField()
_EMPTY = Value("", _TEXT)


def canonical_category(value) -> str:
    category = _NOT_ALPHANUMERIC.sub(" ", str(value or "").upper()).strip()
    return _CATEGORY_ALIASES.get(category, category)


def _manufacturer_names(value) -> list[str]:
    """`Alliant Power / Bosch` son dos marcas sueltas."""
    return [part.strip() for part in str(value or "").split("/") if part.strip()]


def _distinct(queryset, column: str) -> list[str]:
    values = queryset.exclude(**{f"{column}__isnull": True}).values_list(column, flat=True)
    return sorted({str(value).strip() for value in values.distinct() if str(value).strip()})


def _price_bound(value) -> float | None:
    """Vacío o ilegible no acota. El comprador puede escribir `$1,000`."""
    text = re.sub(r"[$,\s]", "", str(value or ""))
    if not text:
        return None
    try:
        amount = float(text)
    except ValueError:
        return None
    return amount if math.isfinite(amount) else None


def _positive_int(value, default: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if number >= 1 else default


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


class _CompactPartNumbers(Func):
    """Los números de parte del producto en minúsculas y sin guiones ni
    espacios, separados por `|`: así `502550` encuentra `502-550` y una
    búsqueda nunca une dos números distintos."""

    function = "regexp_replace"
    template = "regexp_replace(translate(%(expressions)s, '/,', '||'), '[^a-z0-9|]', '', 'g')"


def _text_query(term: str) -> Q:
    query = Q()
    for column in _TEXT_COLUMNS:
        query |= Q(**{f"{column}__icontains": term})
    for key in _TEXT_ATTRIBUTES:
        query |= Q(**{f"attributes__{key}__icontains": term})
    compact = _compact(term)
    if compact:
        query |= Q(part_numbers__contains=compact)
    return query


def _with_part_numbers(queryset):
    numbers = [Coalesce(F("part_number"), _EMPTY)]
    for key in _PART_NUMBER_ATTRIBUTES:
        numbers += [Value("|", _TEXT), Coalesce(KT(f"attributes__{key}"), _EMPTY)]
    return queryset.annotate(
        part_numbers=_CompactPartNumbers(
            Lower(Concat(*numbers, output_field=_TEXT)), output_field=_TEXT
        )
    )


def _vehicle(params) -> dict | None:
    vehicle = {key: str(params.get(key) or "").strip() for key in _VEHICLE_PARAMS}
    return vehicle if any(vehicle.values()) else None


def _series(value) -> set[str]:
    return {a or b for a, b in _SERIES.findall(str(value or "").upper())}


def _engines_differ(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and abs(left - right) > 0.11


def _application_codes(vehicle: dict, year: int) -> list[str]:
    """La aplicación elegida en el garaje, o las que le caben a un vehículo de
    VIN: misma marca, año dentro del rango y la misma cilindrada. Un dato
    ausente no descarta."""
    if vehicle["applicationId"]:
        return [vehicle["applicationId"]]
    makes = _makes(vehicle["vehicleMake"])
    liters = _displacement(vehicle["vehicleEngine"])
    codes = []
    for application in Application.objects.all():
        if makes and not (_makes(application.make) & makes):
            continue
        if year and not (application.year_from or 0) <= year <= (application.year_to or 9999):
            continue
        if _engines_differ(liters, _displacement(application.engine)):
            continue
        codes.append(application.code)
    return codes


def _fits_by_text(product: Product, vehicle: dict) -> bool:
    """Un producto sin filas de compatibilidad se decide por su texto."""
    makes = _makes(vehicle["vehicleMake"])
    if makes and not (_makes(product.make) & makes):
        return False
    wanted, offered = _series(vehicle["vehicleModel"]), _series(product.model)
    if wanted and offered and not (wanted & offered):
        return False
    attributes = product.attributes or {}
    product_liters = _displacement(
        attributes.get("engine"),
        attributes.get("engineFamily"),
        attributes.get("engineCode"),
        attributes.get("fitment"),
    )
    return not _engines_differ(_displacement(vehicle["vehicleEngine"]), product_liters)


def _vehicle_filter(queryset, vehicle: dict):
    year = int(to_number(vehicle["vehicleYear"], 0))
    if year:
        # Una aplicación cubre varios años y el producto puede cubrir solo parte.
        queryset = queryset.filter(
            Q(year_from__isnull=True) | Q(year_from__lte=year),
            Q(year_to__isnull=True) | Q(year_to__gte=year),
        )
    has_rows = Exists(ProductFitment.objects.filter(product=OuterRef("pk")))
    listed = Exists(
        ProductFitment.objects.filter(
            product=OuterRef("pk"), application__code__in=_application_codes(vehicle, year)
        )
    )
    by_text = [
        product.pk
        for product in queryset.filter(~has_rows).only("id", "make", "model", "attributes")
        if _fits_by_text(product, vehicle)
    ]
    return queryset.filter(listed | Q(pk__in=by_text))


def _facets(active) -> dict:
    """Opciones de los filtros: salen de todo el catálogo activo, no de la
    página ni de la búsqueda."""
    brands = {
        name for value in _distinct(active, "manufacturer") for name in _manufacturer_names(value)
    }
    ceiling = active.aggregate(max=Max("price"))["max"] or 0
    return {
        "brands": sorted(brands),
        "categories": _distinct(active, "category"),
        "conditions": _distinct(active, "condition"),
        "priceCeiling": math.ceil(ceiling),
    }


def search_products(params) -> dict:
    """La página pedida, con sus totales; `products` es la lista de filas
    listas para serializar. Con `ids` no hay página ni `facets`: es la consulta
    del carrito por sus propios productos."""
    active = Product.objects.filter(active=True)
    queryset = _with_part_numbers(active).annotate(
        price_or_zero=Coalesce(F("price"), Value(0, _MONEY))
    )

    ids = [part.strip() for part in str(params.get("ids") or "").split(",") if part.strip()]
    if ids:
        queryset = queryset.filter(pk__in=ids[:MAX_PAGE_SIZE])

    term = str(params.get("q") or "").strip()
    if term:
        queryset = queryset.filter(_text_query(term))

    category = canonical_category(params.get("category"))
    if category and category != "ALL":
        queryset = queryset.filter(
            category__in=[
                raw for raw in _distinct(active, "category") if canonical_category(raw) == category
            ]
        )

    brand = str(params.get("brand") or "").strip().lower()
    if brand:
        queryset = queryset.filter(
            manufacturer__in=[
                raw
                for raw in active.exclude(manufacturer__isnull=True)
                .values_list("manufacturer", flat=True)
                .distinct()
                if brand in (name.lower() for name in _manufacturer_names(raw))
            ]
        )

    condition = str(params.get("condition") or "").strip()
    if condition:
        queryset = queryset.filter(condition__iexact=condition)

    minimum, maximum = _price_bound(params.get("min")), _price_bound(params.get("max"))
    if minimum is not None:
        queryset = queryset.filter(price_or_zero__gte=minimum)
    if maximum is not None:
        queryset = queryset.filter(price_or_zero__lte=maximum)

    vehicle = _vehicle(params)
    if vehicle:
        queryset = _vehicle_filter(queryset, vehicle)

    sort = params.get("sort")
    if sort == "low":
        queryset = queryset.order_by("price_or_zero", "id")
    elif sort == "high":
        queryset = queryset.order_by("-price_or_zero", "id")
    else:
        queryset = queryset.order_by("id")

    count = queryset.count()
    page_size = (
        MAX_PAGE_SIZE
        if ids
        else min(_positive_int(params.get("pageSize"), DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE)
    )
    page_count = max(1, math.ceil(count / page_size))
    page = min(_positive_int(params.get("page"), 1), page_count)
    start = (page - 1) * page_size
    result = {
        "count": count,
        "page": page,
        "pageSize": page_size,
        "pageCount": page_count,
        "products": list(
            queryset.prefetch_related("applications", "images")[start : start + page_size]
        ),
    }
    if not ids:
        result["facets"] = _facets(active)
    return result
