from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone
from django.utils.text import slugify

# Deja lugar para el sufijo numérico (`-2`, `-3`...) sin pasar el largo de la columna.
SLUG_MAX_LENGTH = 120
_SLUG_BASE_LENGTH = SLUG_MAX_LENGTH - 8


def product_slug_base(data: dict, product_id: str) -> str:
    """Slug legible del título más el número de parte, sin el sufijo de
    unicidad. El número de parte no se repite si el título ya lo contiene; sin
    título ni número de parte cae al id, que siempre existe."""
    title = slugify(str(data.get("title") or ""))
    part = slugify(
        str(data.get("partNumber") or data.get("oemPart") or data.get("aftermarketPart") or "")
    )
    if part and f"-{part}-" in f"-{title}-":
        part = ""
    base = "-".join(chunk for chunk in (title, part) if chunk) or slugify(str(product_id))
    return base[:_SLUG_BASE_LENGTH].strip("-") or "product"


class Product(models.Model):
    id = models.TextField(primary_key=True)
    # Se genera al crear y nunca cambia al editar: es la URL pública
    # (`/product/<slug>`) que indexan los buscadores.
    slug = models.SlugField(max_length=SLUG_MAX_LENGTH, unique=True)
    data = models.JSONField(default=dict)
    active = models.BooleanField(default=True, db_default=True)
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now())
    # Fitment normalizado; sin filas, el checkout cae al texto de `data`.
    applications = models.ManyToManyField(
        "catalog.Application",
        through="catalog.ProductFitment",
        related_name="products",
        blank=True,
    )

    class Meta:
        db_table = "products"
        indexes = [GinIndex(fields=["data"], name="idx_products_data")]
        permissions = [
            ("edit_pricing", "Can edit pricing"),
            ("view_costs", "Can view costs"),
        ]

    def __str__(self) -> str:
        return self.id

    def save(self, *args, **kwargs):
        # Vive en el modelo y no en un service porque los productos nacen por
        # tres vías (panel, `import_catalog` y el ORM de los tests) y todas
        # necesitan el slug antes del INSERT.
        if not self.slug:
            self.slug = self._unique_slug()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "slug"}
        super().save(*args, **kwargs)

    def _unique_slug(self) -> str:
        base = product_slug_base(self.data or {}, self.pk)
        taken = set(
            Product.objects.filter(slug__startswith=base)
            .exclude(pk=self.pk)
            .values_list("slug", flat=True)
        )
        candidate, suffix = base, 2
        while candidate in taken:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate
