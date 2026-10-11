# Los campos de `applications.data` (marca, modelos, años, motor) pasan a
# columnas tipadas, que el fitment puede filtrar en SQL. El JSON, renombrado a
# `attributes`, se queda con lo demás. Un valor que no entra en su columna
# (un año que no es número, años invertidos) se queda en `attributes` en lugar
# de perderse o de frenar la migración.
import django.contrib.postgres.fields
from django.db import migrations, models

# Copia congelada de `COLUMN_FIELDS` de `apps/catalog/models/application.py`:
# una migración no importa código de la app.
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

_TEXT = models.TextField(blank=True, null=True)
_YEAR = models.PositiveSmallIntegerField(blank=True, null=True)
_BOOL = models.BooleanField(blank=True, null=True)
_LIST = django.contrib.postgres.fields.ArrayField(
    base_field=models.TextField(), blank=True, null=True, size=None
)
_FIELDS = {"text": _TEXT, "year": _YEAR, "bool": _BOOL, "list": _LIST}


def _convert(kind, value):
    """El valor de la columna, o `None` si no entra (y queda en el JSON)."""
    if kind == "text":
        return str(value)
    if kind == "bool":
        return value if isinstance(value, bool) else None
    if kind == "list":
        return [str(entry) for entry in value] if isinstance(value, list) else None
    if isinstance(value, bool):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if year >= 0 else None


def move_to_columns(apps, schema_editor):
    Application = apps.get_model("catalog", "Application")
    for application in Application.objects.all():
        attributes = dict(application.attributes or {})
        columns = {}
        for key, (column, kind) in COLUMN_FIELDS.items():
            value = attributes.get(key)
            if value is None or value == "":
                attributes.pop(key, None)
                continue
            converted = _convert(kind, value)
            if converted is not None:
                columns[column] = converted
                attributes.pop(key)
        year_from, year_to = columns.get("year_from"), columns.get("year_to")
        if year_from is not None and year_to is not None and year_to < year_from:
            attributes["yearFrom"] = columns.pop("year_from")
            attributes["yearTo"] = columns.pop("year_to")
        for column, value in columns.items():
            setattr(application, column, value)
        application.attributes = attributes
        application.save(update_fields=[*columns, "attributes"])


def move_to_json(apps, schema_editor):
    Application = apps.get_model("catalog", "Application")
    for application in Application.objects.all():
        attributes = dict(application.attributes or {})
        for key, (column, _kind) in COLUMN_FIELDS.items():
            value = getattr(application, column)
            if value is not None:
                attributes[key] = value
        application.attributes = attributes
        application.save(update_fields=["attributes"])


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0003_product_columns"),
    ]

    operations = [
        migrations.RenameField(model_name="application", old_name="data", new_name="attributes"),
        *(
            migrations.AddField(
                model_name="application", name=column, field=_FIELDS[kind].clone()
            )
            for column, kind in COLUMN_FIELDS.values()
        ),
        migrations.AlterField(
            model_name="application",
            name="make",
            field=models.TextField(blank=True, db_index=True, null=True),
        ),
        # Antes del CHECK: así valida los valores ya movidos.
        migrations.RunPython(move_to_columns, move_to_json),
        migrations.AddConstraint(
            model_name="application",
            constraint=models.CheckConstraint(
                condition=models.Q(("year_to__gte", models.F("year_from"))),
                name="applications_year_range",
            ),
        ),
    ]
