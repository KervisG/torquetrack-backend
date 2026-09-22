# `first_name` y `last_name` viven en `users`. El ALTER real está en
# `scripts/schema.sql`; aquí solo se registra el estado.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tt_auth", "0004_roles"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="user",
                    name="first_name",
                    field=models.TextField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="user",
                    name="last_name",
                    field=models.TextField(blank=True, null=True),
                ),
            ],
            database_operations=[],
        ),
    ]
