# `customers` pasa a ser una tabla administrada por Django.
#
# El proyecto no está en producción, así que la tabla heredada de
# `scripts/schema.sql` se descarta (si existe) y Django la crea desde su
# estado. No se usa DeleteModel porque `Quote` y `Order` tienen FK de estado
# a `Customer`. Después, las operaciones reales dejan la forma final: sin
# credenciales (viven en `User`) y con el vínculo 1:1 opcional a la cuenta.
#
# El DROP ... CASCADE también quita las FK SQL de `quotes`/`orders` en una
# base de desarrollo existente; `schema.sql` las vuelve a declarar en una
# base nueva porque ahora corre después de `migrate`.
import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


def create_customers_table(apps, schema_editor):
    schema_editor.create_model(apps.get_model("customers", "Customer"))


def drop_customers_table(apps, schema_editor):
    schema_editor.delete_model(apps.get_model("customers", "Customer"))


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0002_customer_permissions"),
        ("tt_auth", "0007_managed_user"),
    ]

    operations = [
        migrations.RunSQL(
            "DROP TABLE IF EXISTS customers CASCADE",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterModelOptions(
                    name="customer",
                    options={
                        "permissions": [
                            ("review_tax_exemption", "Can review tax exemptions"),
                        ],
                    },
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(create_customers_table, drop_customers_table),
        migrations.RemoveField(model_name="customer", name="password_hash"),
        migrations.RemoveField(model_name="customer", name="portal_status"),
        migrations.AlterField(
            model_name="customer",
            name="email",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="customer",
            name="tax_status",
            field=models.TextField(db_default="NOT SUBMITTED", default="NOT SUBMITTED"),
        ),
        migrations.AlterField(
            model_name="customer",
            name="created_at",
            field=models.DateTimeField(
                db_default=django.db.models.functions.datetime.Now()
            ),
        ),
        migrations.AlterField(
            model_name="customer",
            name="updated_at",
            field=models.DateTimeField(
                db_default=django.db.models.functions.datetime.Now()
            ),
        ),
        migrations.AddField(
            model_name="customer",
            name="user",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="customer",
                to="tt_auth.user",
            ),
        ),
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(
                condition=models.Q(("user__isnull", True)),
                fields=("email",),
                name="customers_guest_email_unique",
            ),
        ),
    ]
