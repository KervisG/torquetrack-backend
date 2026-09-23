# `users` pasa a ser una tabla administrada por Django.
#
# El proyecto no está en producción y sus datos no importan, así que la
# tabla heredada de `scripts/schema.sql` se descarta (si existe) y se crea
# de nuevo con la forma final: `email` en lugar de `username`, sin el texto
# `role` ni el JSON `permissions`, y con `role` como FK a `roles`.
# `EmployeeRole` desaparece: el Role cuelga directo del User.
#
# El `ContentType` `tt_auth.user` sobrevive al DeleteModel de estado, así
# que el Permission `manage_users` y los Roles que lo tienen no cambian.
import django.db.models.deletion
import django.db.models.functions.datetime
import django.utils.timezone
from django.db import migrations, models

import apps.auth.models.user


class Migration(migrations.Migration):

    dependencies = [
        ("tt_auth", "0006_permissions_on_models"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="User")],
            database_operations=[
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS users CASCADE",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        migrations.CreateModel(
            name="User",
            fields=[
                (
                    "id",
                    models.TextField(
                        default=apps.auth.models.user.new_user_id,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("email", models.TextField(unique=True)),
                ("password_hash", models.TextField()),
                ("active", models.BooleanField(default=True)),
                ("first_name", models.TextField(blank=True, null=True)),
                ("last_name", models.TextField(blank=True, null=True)),
                ("display_name", models.TextField(blank=True, null=True)),
                (
                    "created_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
                (
                    "role",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="users",
                        to="tt_auth.role",
                    ),
                ),
            ],
            options={
                "db_table": "users",
                "default_permissions": (),
                "permissions": [("manage_users", "Can manage users")],
            },
        ),
        migrations.DeleteModel(name="EmployeeRole"),
    ]
