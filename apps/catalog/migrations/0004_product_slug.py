# Slug SEO de cada producto (`/product/<slug>`), en dos pasos: esta migración
# agrega la columna nullable y la completa para las filas existentes; la
# siguiente la vuelve obligatoria y única. Van separadas porque Postgres no
# deja alterar la tabla en la misma transacción que acaba de actualizar sus
# filas.
#
# La regla se copia aquí a propósito (en lugar de importar el modelo): una
# migración tiene que seguir dando el mismo resultado aunque el código cambie.
from django.db import migrations, models
from django.utils.text import slugify

_SLUG_BASE_LENGTH = 112


def _base(data, product_id):
    title = slugify(str(data.get("title") or ""))
    part = slugify(
        str(data.get("partNumber") or data.get("oemPart") or data.get("aftermarketPart") or "")
    )
    if part and f"-{part}-" in f"-{title}-":
        part = ""
    base = "-".join(chunk for chunk in (title, part) if chunk) or slugify(str(product_id))
    return base[:_SLUG_BASE_LENGTH].strip("-") or "product"


def backfill_slugs(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    taken = set()
    # Orden fijo: el producto más viejo por id se queda con el slug sin sufijo.
    for product in Product.objects.order_by("id").only("id", "data"):
        base = _base(product.data or {}, product.pk)
        candidate, suffix = base, 2
        while candidate in taken:
            candidate = f"{base}-{suffix}"
            suffix += 1
        taken.add(candidate)
        Product.objects.filter(pk=product.pk).update(slug=candidate)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0003_managed_catalog"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="slug",
            field=models.SlugField(max_length=120, null=True),
        ),
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
    ]
