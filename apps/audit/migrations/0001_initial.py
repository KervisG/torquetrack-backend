# `ActivityLog` pasa de `apps.backoffice` (retirada) a `apps.audit`.
#
# El proyecto no está en producción y la bitácora no tiene datos que
# conservar: se descarta la tabla que dejó `backoffice` (si existe) y se crea
# desde el modelo. El permiso `view_activitylog` lo crea Django al migrar y
# lo siembra en los Roles `authorization.0002_seed_roles`.
import django.db.models.functions.datetime
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.RunSQL(
            "DROP TABLE IF EXISTS activity_logs CASCADE",
            reverse_sql=migrations.RunSQL.noop,
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
            },
        ),
    ]
