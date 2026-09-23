# `products` y `applications` pasan a ser tablas administradas por Django.
#
# El proyecto no está en producción y sus datos no importan: la tabla
# heredada de `scripts/schema.sql` se descarta (si existe) y se crea de nuevo
# desde el modelo. El `DeleteModel` de estado conserva el `ContentType`, así
# que los permisos `edit_pricing`/`view_costs` y los Roles que los tienen no
# cambian.
import django.contrib.postgres.indexes
import django.db.models.functions.datetime
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_product_permissions"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="Product"),
                migrations.DeleteModel(name="Application"),
            ],
            database_operations=[
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS products CASCADE;"
                    " DROP TABLE IF EXISTS applications CASCADE",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.TextField(primary_key=True, serialize=False)),
                ("data", models.JSONField(default=dict)),
                ("active", models.BooleanField(db_default=True, default=True)),
                (
                    "updated_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
            ],
            options={
                "db_table": "products",
                "permissions": [
                    ("edit_pricing", "Can edit pricing"),
                    ("view_costs", "Can view costs"),
                ],
                "indexes": [
                    django.contrib.postgres.indexes.GinIndex(
                        fields=["data"], name="idx_products_data"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Application",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("data", models.JSONField(default=dict)),
            ],
            options={
                "db_table": "applications",
            },
        ),
    ]
