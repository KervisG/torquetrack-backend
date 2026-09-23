# `quotes` pasa a ser una tabla administrada por Django.
#
# El proyecto no está en producción: la tabla heredada de
# `scripts/schema.sql` se descarta (si existe) y se crea desde el modelo,
# ahora con la FK real a `customers` (on delete set null) y la restricción
# única sobre `number`. El `DeleteModel` de estado conserva el `ContentType`
# y los permisos `send_quote`/`convert_quote`.
import django.db.models.deletion
import django.db.models.functions.datetime
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("quotes", "0002_quote_permissions"),
        ("customers", "0003_managed_customer"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="Quote")],
            database_operations=[
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS quotes CASCADE",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        migrations.CreateModel(
            name="Quote",
            fields=[
                ("id", models.TextField(primary_key=True, serialize=False)),
                ("number", models.TextField(unique=True)),
                ("status", models.TextField(db_default="BUILDING", default="BUILDING")),
                ("data", models.JSONField(default=dict)),
                (
                    "created_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                (
                    "updated_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="quotes",
                        to="customers.customer",
                    ),
                ),
            ],
            options={
                "db_table": "quotes",
                "permissions": [
                    ("send_quote", "Can send quotes"),
                    ("convert_quote", "Can convert quotes"),
                ],
            },
        ),
    ]
