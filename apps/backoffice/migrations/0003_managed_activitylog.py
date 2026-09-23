# `activity_logs` pasa a ser una tabla administrada por Django.
#
# El proyecto no está en producción: la tabla heredada de
# `scripts/schema.sql` se descarta (si existe) y se crea desde el modelo. El
# `DeleteModel` de estado conserva el `ContentType` y el permiso
# `view_dashboard`.
import django.db.models.functions.datetime
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("backoffice", "0002_activitylog_permissions"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="ActivityLog")],
            database_operations=[
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS activity_logs CASCADE",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        migrations.CreateModel(
            name="ActivityLog",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("actor_id", models.TextField(blank=True, null=True)),
                ("action", models.TextField()),
                ("entity_type", models.TextField(blank=True, null=True)),
                ("entity_id", models.TextField(blank=True, null=True)),
                ("data", models.JSONField(db_default={}, default=dict)),
                (
                    "created_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
            ],
            options={
                "db_table": "activity_logs",
                "permissions": [("view_dashboard", "Can view dashboard")],
            },
        ),
    ]
