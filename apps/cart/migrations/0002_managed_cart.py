# `carts` pasa a ser una tabla administrada por Django.
#
# El proyecto no está en producción: la tabla heredada de
# `scripts/schema.sql` se descarta (si existe) y se crea desde el modelo.
import django.db.models.functions.datetime
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cart", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="Cart")],
            database_operations=[
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS carts CASCADE",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        migrations.CreateModel(
            name="Cart",
            fields=[
                ("id", models.TextField(primary_key=True, serialize=False)),
                ("data", models.JSONField(default=dict)),
                (
                    "updated_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
            ],
            options={
                "db_table": "carts",
            },
        ),
    ]
