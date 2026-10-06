# Fitment normalizado: `product_fitments` (producto ↔ aplicación) y
# `applications.code`, el id estable de la aplicación (`data.id` de la semilla)
# que la relación necesita porque el `id` numérico cambia al reimportar.
#
# En dos pasos, como el slug de `0004`/`0005`: esta migración crea la tabla,
# agrega `code` nullable y lo completa; la siguiente lo vuelve obligatorio y
# único, porque Postgres no deja alterar la tabla en la misma transacción que
# acaba de actualizar sus filas. El `ON DELETE CASCADE` de las FK también va en
# la siguiente: Django crea las FK al final de la migración, después de
# cualquier `RunSQL`.
#
# Las filas de `product_fitments` NO se crean aquí: las arma
# `manage.py backfill_product_fitment`, que reporta lo que no pudo leer.
import django.db.models.deletion
from django.db import migrations, models


def fill_application_codes(apps, schema_editor):
    """`data.id` es el código; uno ausente o repetido cae a
    `application-<pk>` para no inventar a qué aplicación se refería."""
    Application = apps.get_model("catalog", "Application")
    taken = set()
    for application in Application.objects.order_by("id").only("id", "data"):
        code = str((application.data or {}).get("id") or "").strip()[:120]
        if not code or code in taken:
            code = f"application-{application.pk}"
        taken.add(code)
        Application.objects.filter(pk=application.pk).update(code=code)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0005_product_slug_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="code",
            field=models.CharField(max_length=120, null=True),
        ),
        migrations.CreateModel(
            name="ProductFitment",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fitments",
                        to="catalog.application",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fitments",
                        to="catalog.product",
                    ),
                ),
            ],
            options={
                "db_table": "product_fitments",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("product", "application"), name="product_fitments_unique"
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="product",
            name="applications",
            field=models.ManyToManyField(
                blank=True,
                related_name="products",
                through="catalog.ProductFitment",
                to="catalog.application",
            ),
        ),
        migrations.RunPython(fill_application_codes, migrations.RunPython.noop),
    ]
