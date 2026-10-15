# Crea una categoría por cada una que ya llevan los productos en `category`,
# en la línea de la portada que el SPA tenía escrita a mano. Los alias y las
# líneas van copiados acá: una migración no depende de código que cambia.
import re

from django.db import migrations

ALIASES = {
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
LINES = {
    "FUEL_SYSTEM": ("INJECTOR", "HPFP", "HPOP", "FUEL RAIL", "CONTAMINATION KIT"),
    "TURBO_AIR": ("TURBO", "TURBO ACTUATOR"),
    "EMISSIONS": ("DPF", "DOC", "SCR", "EGR"),
}
LINE_OF = {value: line for line, values in LINES.items() for value in values}
NOT_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")


def _canonical(raw: str) -> str:
    value = NOT_ALPHANUMERIC.sub(" ", raw.upper()).strip()
    return ALIASES.get(value, value)


def seed_categories(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    Product = apps.get_model("catalog", "Product")
    existing = set(Category.objects.values_list("value", flat=True))
    names = (
        Product.objects.exclude(category__isnull=True)
        .order_by("category")
        .values_list("category", flat=True)
        .distinct()
    )
    for raw in names:
        name = str(raw).strip()
        value = _canonical(name)
        if value and value not in existing:
            Category.objects.create(name=name, value=value, line=LINE_OF.get(value, "OTHER"))
            existing.add(value)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0008_categories"),
    ]

    operations = [
        # Al revertir no hay nada que deshacer: `0008` borra la tabla.
        migrations.RunPython(seed_categories, migrations.RunPython.noop),
    ]
