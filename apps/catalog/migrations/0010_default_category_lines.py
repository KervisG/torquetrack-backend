# `import_catalog` creaba en `OTHER` las categorías que traían los productos,
# así un servidor cargado con la semilla o con el ZIP del panel perdía la
# sección de la portada. Esto devuelve a su sección las categorías conocidas
# que quedaron en `OTHER`; corre una sola vez, después manda el panel. Las
# líneas van copiadas acá: una migración no depende de código que cambia.
from django.db import migrations

LINES = {
    "FUEL_SYSTEM": ("INJECTOR", "HPFP", "HPOP", "FUEL RAIL", "CONTAMINATION KIT"),
    "TURBO_AIR": ("TURBO", "TURBO ACTUATOR"),
    "EMISSIONS": ("DPF", "DOC", "SCR", "EGR"),
}


def restore_default_lines(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    for line, values in LINES.items():
        Category.objects.filter(value__in=values, line="OTHER").update(line=line)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0009_seed_categories"),
    ]

    operations = [
        # Al revertir no se sabe cuáles estaban en `OTHER` a propósito.
        migrations.RunPython(restore_default_lines, migrations.RunPython.noop),
    ]
