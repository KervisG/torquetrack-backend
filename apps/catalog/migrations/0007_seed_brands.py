# Crea una marca por cada nombre que ya llevan los productos en
# `manufacturer`. `Alliant Power / Bosch` son dos marcas, igual que en el
# filtro de la tienda; gana la primera forma de escribir cada nombre.
from django.db import migrations


def seed_brands(apps, schema_editor):
    Brand = apps.get_model("catalog", "Brand")
    Product = apps.get_model("catalog", "Product")
    existing = {name.lower() for name in Brand.objects.values_list("name", flat=True)}
    manufacturers = (
        Product.objects.exclude(manufacturer__isnull=True)
        .order_by("manufacturer")
        .values_list("manufacturer", flat=True)
        .distinct()
    )
    for manufacturer in manufacturers:
        for name in (part.strip() for part in str(manufacturer).split("/")):
            if name and name.lower() not in existing:
                Brand.objects.create(name=name)
                existing.add(name.lower())


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0006_brands"),
    ]

    operations = [
        # Al revertir no hay nada que deshacer: `0006` borra la tabla.
        migrations.RunPython(seed_brands, migrations.RunPython.noop),
    ]
