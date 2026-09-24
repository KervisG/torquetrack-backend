from django.db import migrations, models


class Migration(migrations.Migration):
    """Adopta la tabla `document_sequences` que creó `checkout`; no la vuelve a
    crear, así la numeración ya emitida no se reinicia."""

    initial = True

    dependencies = [
        ("checkout", "0004_move_document_sequence"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="DocumentSequence",
                    fields=[
                        ("key", models.TextField(primary_key=True, serialize=False)),
                        ("last_value", models.PositiveBigIntegerField()),
                    ],
                    options={
                        "db_table": "document_sequences",
                        "default_permissions": (),
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
