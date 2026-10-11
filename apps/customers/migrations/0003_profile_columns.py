# El perfil del cliente (nombre, empresa, teléfono y dirección) pasa de
# `customers.data` a columnas. El JSON, renombrado a `details`, guarda el resto
# (la exención de impuestos). Un valor que no es texto se guarda como texto.
from django.db import migrations, models

# Copia congelada de `PROFILE_COLUMNS` de `apps/customers/models/customer.py`.
PROFILE_COLUMNS = ("name", "company", "phone", "address1", "address2", "city", "state", "zip")


def move_to_columns(apps, schema_editor):
    Customer = apps.get_model("customers", "Customer")
    for customer in Customer.objects.all():
        details = dict(customer.details or {})
        for column in PROFILE_COLUMNS:
            value = details.pop(column, None)
            setattr(customer, column, None if value in (None, "") else str(value))
        customer.details = details
        customer.save(update_fields=[*PROFILE_COLUMNS, "details"])


def move_to_json(apps, schema_editor):
    Customer = apps.get_model("customers", "Customer")
    for customer in Customer.objects.all():
        profile = {
            column: getattr(customer, column)
            for column in PROFILE_COLUMNS
            if getattr(customer, column) is not None
        }
        customer.details = {**(customer.details or {}), **profile}
        customer.save(update_fields=["details"])


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0002_db_on_delete"),
    ]

    operations = [
        migrations.RenameField(model_name="customer", old_name="data", new_name="details"),
        *(
            migrations.AddField(
                model_name="customer",
                name=column,
                field=models.TextField(blank=True, null=True),
            )
            for column in PROFILE_COLUMNS
        ),
        migrations.RunPython(move_to_columns, move_to_json),
    ]
