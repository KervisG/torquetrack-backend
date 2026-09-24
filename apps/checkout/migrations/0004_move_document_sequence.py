from django.db import migrations


class Migration(migrations.Migration):
    """`DocumentSequence` pasa a `apps.numbering`. Solo cambia el estado: la
    tabla `document_sequences` y sus filas quedan intactas."""

    dependencies = [
        ("checkout", "0003_managed_checkout"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="DocumentSequence")],
            database_operations=[],
        ),
    ]
