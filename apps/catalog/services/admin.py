from __future__ import annotations

import re

from django.utils import timezone

from apps.audit.services import record_activity
from apps.catalog.models import Product, ProductFieldError
from apps.catalog.serializers import RESTRICTED_PRODUCT_FIELDS
from apps.catalog.services.fitment import (
    application_codes,
    resolve_application_codes,
    set_product_applications,
)
from apps.common.business_day import store_today
from apps.common.errors import error_payload
from apps.common.numbers import money_decimal

PRICE_FIELDS = ("price", "compareAt", "coreCharge")
# Deben seguir incluidos en `RESTRICTED_PRODUCT_FIELDS` de `serializers/storefront.py`.
COST_FIELDS = ("purchaseCost", "supplierCost")
PROTECTED_FIELDS = PRICE_FIELDS + COST_FIELDS
# El formulario los oculta sin `costs.view`. Si el PUT no los trae, se
# conservan: el cliente no puede reenviar lo que la API le tapó.
HIDDEN_WITHOUT_COSTS = RESTRICTED_PRODUCT_FIELDS + (
    "supplier",
    "supplierUrl",
    "supplierPartNumber",
)


def product_price_error(product_data: dict) -> str | None:
    """Todo producto se vende con precio: ausente, cero o negativo es inválido.
    Lo aplican el panel y `import_catalog`, las dos vías de carga."""
    if money_decimal(product_data.get("price")) <= 0:
        return "price must be greater than 0"
    return None


# Mismas reglas y mensajes que `src/lib/validators/admin-product.ts` del SPA.
TITLE_REQUIRED = "Title is required"
PART_NUMBER_REQUIRED = "Part number is required"
INVALID_YEAR = "Enter a 4-digit year"
YEAR_ORDER = "Year to must be the same as or after year from"
MIN_PRODUCT_YEAR = 1900
# Los modelos del año próximo salen a la venta antes de que empiece.
YEARS_AHEAD = 2
_FOUR_DIGITS = re.compile(r"\d{4}")


def max_product_year() -> int:
    return store_today().year + YEARS_AHEAD


def year_range_error() -> str:
    return f"Enter a year between {MIN_PRODUCT_YEAR} and {max_product_year()}"


def _required_text(product_data: dict, key: str) -> str | None:
    value = product_data.get(key)
    return value.strip() or None if isinstance(value, str) else None


def _year(value) -> int | str | None:
    """El año como `int`, `None` si viene vacío, o el mensaje de error.

    Acepta el número del JSON o el texto de 4 dígitos; un `bool` o un decimal
    no son un año aunque Python los compare como números."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str) and _FOUR_DIGITS.fullmatch(value.strip()):
        value = int(value.strip())
    if type(value) is not int or not 1000 <= value <= 9999:
        return INVALID_YEAR
    if not MIN_PRODUCT_YEAR <= value <= max_product_year():
        return year_range_error()
    return value


def clean_product_fields(product_data: dict) -> tuple[str, str] | None:
    """Valida y normaliza en el lugar el título, el número de parte y los años.

    Devuelve `(mensaje, campo)` del primer error, o `None`. El número de parte
    no es único: el catálogo de origen repite números entre aplicaciones."""
    title = _required_text(product_data, "title")
    if title is None:
        return TITLE_REQUIRED, "title"
    part_number = _required_text(product_data, "partNumber")
    if part_number is None:
        return PART_NUMBER_REQUIRED, "partNumber"
    years = {}
    for key in ("yearFrom", "yearTo"):
        year = _year(product_data.get(key))
        if isinstance(year, str):
            return year, key
        years[key] = year
    if years["yearFrom"] and years["yearTo"] and years["yearTo"] < years["yearFrom"]:
        return YEAR_ORDER, "yearTo"

    product_data["title"] = title
    product_data["partNumber"] = part_number
    for key, year in years.items():
        # Vacío es "sin dato": no se guarda un "" ni un `null`.
        if year is None:
            product_data.pop(key, None)
        else:
            product_data[key] = year
    return None


def serialize_admin_product(data: dict, *, can_view_costs: bool) -> dict:
    if can_view_costs:
        return dict(data)
    return {key: value for key, value in data.items() if key not in HIDDEN_WITHOUT_COSTS}


def upsert_admin_product(
    product_id: str,
    payload: dict,
    actor_email: str,
    *,
    can_edit_pricing: bool,
    can_view_costs: bool,
) -> tuple[dict, int]:
    """El `id` de la URL gana sobre cualquier `id` del body.

    El PUT reemplaza `data`, salvo los campos de precio y costo ausentes, que
    conservan su valor: quien no ve los costos no puede reenviarlos y no debe
    borrarlos. `active` cambia solo si viene en el body.
    """
    raw = payload.get("product") if isinstance(payload.get("product"), dict) else payload
    # El slug es de la columna y se genera al crear: el panel no lo elige ni lo
    # cambia, así la URL pública de un producto editado sigue valiendo.
    product_data = {key: value for key, value in raw.items() if key not in ("active", "slug")}
    product_data["id"] = product_id
    # El fitment vive en `ProductFitment`, no en `data`. Sin la clave en el
    # body la relación no cambia; con ella (aunque sea `[]`) se reemplaza.
    raw_application_ids = product_data.pop("applicationIds", None)
    applications = None
    if "applicationIds" in raw:
        applications, error = resolve_application_codes(raw_application_ids)
        if error:
            return error_payload(error, "applicationIds"), 400

    active =payload["active"] if "active" in payload else raw.get("active")
    if active is not None and not isinstance(active, bool):
        return error_payload("active must be a boolean", "active"), 400

    product = Product.objects.filter(pk=product_id).first()
    stored = (product.data or {}) if product is not None else {}
    if not can_view_costs:
        for field in HIDDEN_WITHOUT_COSTS:
            if field not in product_data and field in stored:
                product_data[field] = stored[field]
    for field in PROTECTED_FIELDS:
        if field not in product_data and field in stored:
            product_data[field] = stored[field]

    changed = [f for f in PROTECTED_FIELDS if product_data.get(f) != stored.get(f)]
    if changed and not can_edit_pricing:
        return {"error": "Changing prices or costs requires pricing.edit"}, 403
    if error := product_price_error(product_data):
        return error_payload(error, "price"), 400
    if field_error := clean_product_fields(product_data):
        return error_payload(*field_error), 400

    created = product is None
    if created:
        product = Product(id=product_id, active=True if active is None else active)
    elif active is not None:
        product.active = active
    try:
        product.data = product_data
    except ProductFieldError as exc:
        return error_payload(str(exc), exc.field), 400
    product.updated_at = timezone.now()
    product.save()
    if applications is not None:
        set_product_applications(product, applications)

    record_activity(
        actor=actor_email,
        action="PRODUCT_CREATED" if created else "PRODUCT_UPDATED",
        entity_type="PRODUCT",
        entity_id=product_id,
        data={"partNumber": product_data.get("partNumber"), "changedPricing": changed},
    )
    return {
        "ok": True,
        "product": {
            **serialize_admin_product(product_data, can_view_costs=can_view_costs),
            "slug": product.slug,
            "applicationIds": application_codes(product),
        },
    }, 200


def list_admin_products(*, can_view_costs: bool) -> list[dict]:
    """Incluye inactivos: el panel es el único lugar donde se reactivan."""
    rows = []
    for product in Product.objects.prefetch_related("applications").order_by("id"):
        data = serialize_admin_product(product.data or {}, can_view_costs=can_view_costs)
        data["applicationIds"] = application_codes(product)
        data["id"] = product.pk
        data["slug"] = product.slug
        data["active"] = product.active
        rows.append(data)
    return rows


def deactivate_admin_product(product_id: str, actor_email: str) -> tuple[dict, int]:
    updated = Product.objects.filter(pk=product_id).update(
        active=False, updated_at=timezone.now()
    )
    if not updated:
        return {"error": "Product not found"}, 404
    record_activity(
        actor=actor_email,
        action="PRODUCT_DEACTIVATED",
        entity_type="PRODUCT",
        entity_id=product_id,
    )
    return {"ok": True}, 200
