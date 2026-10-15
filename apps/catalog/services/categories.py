"""Categorías del panel: listar, crear y moverlas de línea de la portada, y
llevarlas de un servidor a otro (`categories.json` del ZIP y de la semilla).

Una categoría es el texto que llevan los productos en `category`. Ese texto
se escribe de varias formas (`Injector`, `Fuel Injectors`), así que el vínculo
es por la forma canónica (`canonical_category`) y no una FK. `line` decide en
qué sección de la portada sale; sin fila, una categoría cae en `OTHER`.
"""

from __future__ import annotations

from apps.audit.services import record_activity
from apps.catalog.models import Category, Product, ProductLine
from apps.catalog.services.search import canonical_category
from apps.common.errors import error_payload

NAME_REQUIRED = "Category name is required"
NAME_TAKEN = "A category with this name already exists"
INVALID_LINE = f"line must be one of {', '.join(ProductLine.values)}"
CATEGORY_NOT_FOUND = "Category not found"


def _product_counts() -> dict[str, int]:
    """Productos por categoría canónica. Cuenta activos e inactivos: el panel
    muestra todos."""
    counts: dict[str, int] = {}
    rows = Product.objects.exclude(category__isnull=True).values_list("category", flat=True)
    for category in rows:
        value = canonical_category(category)
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def _serialize(category: Category, product_count: int) -> dict:
    return {
        "id": category.pk,
        "name": category.name,
        "value": category.value,
        "line": category.line,
        "productCount": product_count,
    }


def _category_payload(category: Category) -> dict:
    return {"ok": True, "category": _serialize(category, _product_counts().get(category.value, 0))}


def list_admin_categories() -> list[dict]:
    counts = _product_counts()
    return [
        _serialize(category, counts.get(category.value, 0)) for category in Category.objects.all()
    ]


def ensure_category(raw) -> None:
    """Crea la categoría de un producto si todavía no existe, en `OTHER`. Lo
    llaman las dos vías de carga de productos: el panel y `import_catalog`."""
    name = str(raw or "").strip()
    value = canonical_category(name)
    if value and not Category.objects.filter(value=value).exists():
        Category.objects.create(name=name, value=value)


def export_categories() -> list[dict]:
    """Las filas de `categories.json` del ZIP del panel: nombre y sección."""
    return [{"name": category.name, "line": category.line} for category in Category.objects.all()]


def invalid_category_rows(rows) -> list[str]:
    """Las filas de un `categories.json` que no se pueden importar."""
    if not isinstance(rows, list):
        return ["the file must be a list of {name, line}"]
    errors = []
    for index, row in enumerate(rows):
        name = row.get("name") if isinstance(row, dict) else None
        line = row.get("line", ProductLine.OTHER) if isinstance(row, dict) else None
        if not canonical_category(name if isinstance(name, str) else ""):
            errors.append(f"row {index}: {NAME_REQUIRED}")
        elif line not in ProductLine.values:
            errors.append(f"row {index} ({name}): {INVALID_LINE}")
    return errors


def import_categories(rows: list[dict], *, only_missing: bool) -> int:
    """Crea las categorías que faltan; sin `only_missing` también pone la
    sección del archivo a las que ya existen. El nombre guardado no cambia.
    Las filas ya pasaron por `invalid_category_rows`. Devuelve cuántas creó."""
    created = 0
    for row in rows:
        name = row["name"].strip()
        line = row.get("line", ProductLine.OTHER)
        category = Category.objects.filter(value=canonical_category(name)).first()
        if category is None:
            Category.objects.create(name=name, value=canonical_category(name), line=line)
            created += 1
        elif not only_missing and category.line != line:
            category.line = line
            category.save(update_fields=["line"])
    return created


def create_admin_category(payload: dict, actor_email: str) -> tuple[dict, int]:
    raw = payload.get("name")
    name = raw.strip() if isinstance(raw, str) else ""
    value = canonical_category(name)
    if not value:
        return error_payload(NAME_REQUIRED, "name"), 400
    line = payload.get("line", ProductLine.OTHER)
    if line not in ProductLine.values:
        return error_payload(INVALID_LINE, "line"), 400
    if Category.objects.filter(value=value).exists():
        return error_payload(NAME_TAKEN, "name"), 400

    category = Category.objects.create(name=name, value=value, line=line)
    record_activity(
        actor=actor_email,
        action="CATEGORY_CREATED",
        entity_type="CATEGORY",
        entity_id=str(category.pk),
        data={"name": name, "line": line},
    )
    return _category_payload(category), 201


def set_admin_category_line(category_id, payload: dict, actor_email: str) -> tuple[dict, int]:
    line = payload.get("line")
    if line not in ProductLine.values:
        return error_payload(INVALID_LINE, "line"), 400
    category = Category.objects.filter(pk=category_id).first()
    if category is None:
        return {"error": CATEGORY_NOT_FOUND}, 404

    previous = category.line
    category.line = line
    category.save(update_fields=["line"])
    record_activity(
        actor=actor_email,
        action="CATEGORY_LINE_CHANGED",
        entity_type="CATEGORY",
        entity_id=str(category.pk),
        data={"name": category.name, "from": previous, "to": line},
    )
    return _category_payload(category), 200
