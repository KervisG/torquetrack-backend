from decimal import Decimal, InvalidOperation

from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Now
from django.utils import timezone
from django.utils.text import slugify

from apps.common.numbers import money_decimal

# Deja lugar para el sufijo numérico (`-2`, `-3`...) sin pasar el largo de la columna.
SLUG_MAX_LENGTH = 120
_SLUG_BASE_LENGTH = SLUG_MAX_LENGTH - 8

# Clave camelCase de la API -> (columna, tipo). Lo que no está aquí queda en
# `attributes`, el JSON de los datos descriptivos.
COLUMN_FIELDS = {
    "title": ("title", "text"),
    "partNumber": ("part_number", "text"),
    "price": ("price", "money"),
    "compareAt": ("compare_at", "money"),
    "coreCharge": ("core_charge", "money"),
    "purchaseCost": ("purchase_cost", "money"),
    "stock": ("stock", "text"),
    "make": ("make", "text"),
    "model": ("model", "text"),
    "category": ("category", "text"),
    "yearFrom": ("year_from", "year"),
    "yearTo": ("year_to", "year"),
}


class ProductFieldError(ValueError):
    """Un valor que no entra en su columna; `field` es la clave de la API."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def _to_column(key: str, kind: str, value):
    """Vacío es "sin dato" (`None`), igual que una clave ausente del JSON."""
    if value is None or value == "":
        return None
    if kind == "text":
        return str(value)
    if isinstance(value, bool):
        raise ProductFieldError(key, f"{key} must be a number")
    if kind == "year":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ProductFieldError(key, f"{key} must be a year") from None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ProductFieldError(key, f"{key} must be a number") from None
    if not number.is_finite():
        raise ProductFieldError(key, f"{key} must be a number")
    return money_decimal(number)


def _from_column(kind: str, value):
    # El JSON de la API lleva números, no el texto con que DRF serializa un `Decimal`.
    return float(value) if kind == "money" else value


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
    title = models.TextField(null=True, blank=True)
    # No es único: el catálogo de origen repite números entre aplicaciones.
    part_number = models.TextField(null=True, blank=True, db_index=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    compare_at = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    core_charge = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    purchase_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Disponibilidad en texto libre ("Supplier Check"), no una cantidad.
    stock = models.TextField(null=True, blank=True)
    make = models.TextField(null=True, blank=True)
    model = models.TextField(null=True, blank=True)
    category = models.TextField(null=True, blank=True)
    year_from = models.PositiveSmallIntegerField(null=True, blank=True)
    year_to = models.PositiveSmallIntegerField(null=True, blank=True)
    attributes = models.JSONField(default=dict)
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
        # Un `NULL` pasa los CHECK: "sin dato" sigue siendo válido.
        constraints = [
            *(
                models.CheckConstraint(
                    condition=Q(**{f"{column}__gte": 0}), name=f"products_{column}_non_negative"
                )
                for column in ("price", "compare_at", "core_charge", "purchase_cost")
            ),
            models.CheckConstraint(
                condition=Q(year_to__gte=F("year_from")), name="products_year_range"
            ),
        ]
        permissions = [
            ("edit_pricing", "Can edit pricing"),
            ("view_costs", "Can view costs"),
        ]

    def __str__(self) -> str:
        return self.id

    @property
    def data(self) -> dict:
        """La forma camelCase que consumen la API, el checkout y el panel:
        `attributes` más las columnas con valor."""
        merged = dict(self.attributes or {})
        for key, (column, kind) in COLUMN_FIELDS.items():
            value = getattr(self, column)
            if value is not None:
                merged[key] = _from_column(kind, value)
        return merged

    @data.setter
    def data(self, value: dict) -> None:
        """Reemplaza todo: una clave de columna ausente la deja en `None`.
        `ProductFieldError` si un valor no entra en su columna."""
        remaining = dict(value or {})
        columns = {
            column: _to_column(key, kind, remaining.pop(key, None))
            for key, (column, kind) in COLUMN_FIELDS.items()
        }
        for column, column_value in columns.items():
            setattr(self, column, column_value)
        self.attributes = remaining

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
