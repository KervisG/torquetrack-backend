# Marcador sin tabla. La etiqueta de esta app es `tt_auth` (no `auth`)
# porque `auth` ya es `django.contrib.auth`.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tt_auth", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="TorqueTrackPermission",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "TorqueTrack permission",
                        "managed": False,
                        "default_permissions": (),
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
