from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F, Q

from apps.catalog.models.columns import ColumnDataMixin
from apps.common.ids import random_id

CODE_MAX_LENGTH = 120

# Clave camelCase de la API -> (columna, tipo). Lo que no está aquí queda en
# `attributes`.
COLUMN_FIELDS = {
    "vehicleType": ("vehicle_type", "text"),
    "make": ("make", "text"),
    "models": ("vehicle_models", "list"),
    "yearFrom": ("year_from", "year"),
    "yearTo": ("year_to", "year"),
    "engine": ("engine", "text"),
    "engineCode": ("engine_code", "text"),
    "engineFamily": ("engine_family", "text"),
    "fuelType": ("fuel_type", "text"),
    "vinCompatible": ("vin_compatible", "bool"),
    "serialCompatible": ("serial_compatible", "bool"),
}


class Application(ColumnDataMixin, models.Model):
    """Un rango de años de una marca con un motor (y los modelos que lo montan).

    `code` es el id estable (`ford-73-powerstroke-1994-1997`) que usan el SPA,
    `applicationIds` y la semilla; el `id` numérico lo genera la base y no
    sobrevive a una reimportación, así que nadie fuera de la base lo usa."""

    COLUMN_FIELDS = COLUMN_FIELDS

    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=CODE_MAX_LENGTH, unique=True)
    vehicle_type = models.TextField(null=True, blank=True)
    make = models.TextField(null=True, blank=True, db_index=True)
    # Los modelos que montan el motor en ese rango de años ("F-250", "F-350").
    # No se llama `models`: taparía el módulo de Django dentro de la clase.
    vehicle_models = ArrayField(models.TextField(), null=True, blank=True)
    year_from = models.PositiveSmallIntegerField(null=True, blank=True)
    year_to = models.PositiveSmallIntegerField(null=True, blank=True)
    engine = models.TextField(null=True, blank=True)
    engine_code = models.TextField(null=True, blank=True)
    engine_family = models.TextField(null=True, blank=True)
    fuel_type = models.TextField(null=True, blank=True)
    vin_compatible = models.BooleanField(null=True, blank=True)
    serial_compatible = models.BooleanField(null=True, blank=True)
    attributes = models.JSONField(default=dict)

    class Meta:
        db_table = "applications"
        constraints = [
            # Un `NULL` pasa el CHECK: "sin dato" sigue siendo válido.
            models.CheckConstraint(
                condition=Q(year_to__gte=F("year_from")), name="applications_year_range"
            ),
        ]

    def __str__(self) -> str:
        return self.code or str(self.pk)

    def save(self, *args, **kwargs):
        # Igual que el slug del producto: las aplicaciones nacen por la
        # semilla, el ORM de los tests y migraciones, y todas necesitan el
        # código antes del INSERT.
        if not self.code:
            self.code = str((self.attributes or {}).get("id") or "").strip()[:CODE_MAX_LENGTH] or (
                random_id("APP").lower()
            )
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "code"}
        super().save(*args, **kwargs)
