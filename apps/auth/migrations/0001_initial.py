# Binding Stage A de `users`: el estado de Django registra el modelo y
# `database_operations` queda vacío para que `migrate` no toque la tabla.
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="User",
                    fields=[
                        ("id", models.TextField(primary_key=True, serialize=False)),
                        ("username", models.TextField(unique=True)),
                        ("password_hash", models.TextField()),
                        ("role", models.TextField(default="authorized")),
                        ("active", models.BooleanField(default=True)),
                        ("display_name", models.TextField(blank=True, null=True)),
                        ("permissions", models.JSONField(default=list)),
                        ("created_at", models.DateTimeField()),
                    ],
                    options={
                        "db_table": "users",
                        "managed": False,
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
