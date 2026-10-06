"""Relación producto ↔ aplicación (`ProductFitment`): lectura para la tienda y
el panel, escritura desde el panel y backfill desde el texto de `data`.

El backfill no adivina. `data.applicationIds` manda cuando existe; si ninguno
de esos ids existe el producto queda sin filas y reportado. Solo sin ids se
cruza el texto, y únicamente con marca, rango de años y cilindrada con decimal
(`6.7`) legibles: el modelo no se cruza porque el texto (`C/K 2500 / 3500`) no
tiene un formato que se pueda partir sin suponer."""
from __future__ import annotations

import re

from django.db import transaction

from apps.catalog.models import Application, Product, ProductFitment
from apps.common.numbers import to_number

APPLICATION_IDS_ERROR = "applicationIds must be a list of application ids"
# Cilindrada con decimal: `engineCode` como `L65/L56` o `LB7` no cuenta.
_DISPLACEMENT_RE = re.compile(r"\d{1,2}\.\d")
_MAKE_SPLIT_RE = re.compile(r"\s*(?:/|,|&|\band\b)\s*")
_MAKE_ALIASES = {"chevy": "chevrolet", "dodge": "ram"}
_TEXT_FIELDS = ("make", "model", "yearFrom", "yearTo", "engine", "engineFamily", "engineCode")


def serialize_application(application: Application) -> dict:
    """El `id` público es el código, aunque `data` traiga otro o ninguno."""
    return {**(application.data or {}), "id": application.code}


def list_applications() -> list[dict]:
    """Opciones del selector de vehículos compatibles del editor del panel."""
    return [serialize_application(app) for app in Application.objects.order_by("code")]


def application_codes(product: Product) -> list[str]:
    """Lee `product.applications.all()`: con `prefetch_related("applications")`
    no hace consultas por producto."""
    return sorted(application.code for application in product.applications.all())


def resolve_application_codes(raw) -> tuple[list[Application] | None, str | None]:
    """Valida los `applicationIds` del panel: todos tienen que existir, así un
    id mal tipeado no se descarta en silencio."""
    if not isinstance(raw, list) or not all(isinstance(code, str) for code in raw):
        return None, APPLICATION_IDS_ERROR
    codes = list(dict.fromkeys(code.strip() for code in raw if code.strip()))
    found = {app.code: app for app in Application.objects.filter(code__in=codes)}
    missing = [code for code in codes if code not in found]
    if missing:
        return None, f"Unknown application: {', '.join(missing)}"
    return [found[code] for code in codes], None


def set_product_applications(product: Product, applications: list[Application]) -> None:
    product.applications.set(applications)


def _displacement(*values) -> float | None:
    for value in values:
        match = _DISPLACEMENT_RE.search(str(value or ""))
        if match:
            return float(match.group(0))
    return None


def _makes(value) -> set[str]:
    tokens = _MAKE_SPLIT_RE.split(str(value or "").strip().lower())
    return {_MAKE_ALIASES.get(token, token) for token in tokens if token}


def parse_text_fitment(data: dict) -> dict | None:
    """Marca, años y cilindrada del texto del producto, o `None` si falta
    alguno o el rango no tiene sentido."""
    makes = _makes(data.get("make"))
    year_from = int(to_number(data.get("yearFrom"), 0))
    year_to = int(to_number(data.get("yearTo"), 0)) or year_from
    engine = _displacement(data.get("engine"), data.get("engineFamily"), data.get("engineCode"))
    if not makes or year_from <= 0 or year_to < year_from or engine is None:
        return None
    return {"makes": makes, "yearFrom": year_from, "yearTo": year_to, "engine": engine}


def match_applications(parsed: dict, applications: list[Application]) -> list[Application]:
    matches = []
    for application in applications:
        data = application.data or {}
        app_from = int(to_number(data.get("yearFrom"), 0))
        app_to = int(to_number(data.get("yearTo"), 0)) or app_from
        app_engine = _displacement(data.get("engine"))
        if (
            _makes(data.get("make")) & parsed["makes"]
            and app_engine is not None
            and abs(app_engine - parsed["engine"]) < 0.05
            and app_from
            and app_from <= parsed["yearTo"]
            and app_to >= parsed["yearFrom"]
        ):
            matches.append(application)
    return matches


def _has_text_fitment(data: dict) -> bool:
    return any(str(data.get(field) or "").strip() for field in _TEXT_FIELDS)


def backfill_product_fitments(products, *, replace: bool = False) -> dict:
    """Crea las filas de `ProductFitment` desde `data` sin tocar `data`.

    Sin `replace`, un producto que ya tiene filas (cargadas por el panel o por
    una corrida anterior) se saltea, así correrlo dos veces no cambia nada.
    `import_catalog` pasa `replace=True` porque la semilla manda sobre sus
    productos."""
    applications = list(Application.objects.order_by("code"))
    by_code = {application.code: application for application in applications}
    report = {
        "scanned": 0,
        "linkedFromIds": 0,
        "linkedFromText": 0,
        "links": 0,
        "skippedExisting": 0,
        "noData": 0,
        "unresolved": [],
        "unparseable": [],
        "unmatched": [],
        "unknownApplicationIds": {},
    }
    with transaction.atomic():
        linked = set(
            ProductFitment.objects.filter(product__in=products).values_list(
                "product_id", flat=True
            )
        )
        for product in products.order_by("id"):
            report["scanned"] += 1
            if product.pk in linked:
                if not replace:
                    report["skippedExisting"] += 1
                    continue
                ProductFitment.objects.filter(product=product).delete()

            data = product.data or {}
            raw_ids = data.get("applicationIds")
            ids = (
                [str(code).strip() for code in raw_ids if str(code).strip()]
                if isinstance(raw_ids, list)
                else []
            )
            if ids:
                matches = [by_code[code] for code in dict.fromkeys(ids) if code in by_code]
                unknown = [code for code in dict.fromkeys(ids) if code not in by_code]
                if unknown:
                    report["unknownApplicationIds"][product.pk] = unknown
                if not matches:
                    report["unresolved"].append(product.pk)
                    continue
                report["linkedFromIds"] += 1
            elif not _has_text_fitment(data):
                report["noData"] += 1
                continue
            else:
                parsed = parse_text_fitment(data)
                if parsed is None:
                    report["unparseable"].append(product.pk)
                    continue
                matches = match_applications(parsed, applications)
                if not matches:
                    report["unmatched"].append(product.pk)
                    continue
                report["linkedFromText"] += 1

            ProductFitment.objects.bulk_create(
                ProductFitment(product=product, application=application)
                for application in matches
            )
            report["links"] += len(matches)
    return report
