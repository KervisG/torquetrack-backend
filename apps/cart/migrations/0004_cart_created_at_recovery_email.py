# `created_at` (embudo de carritos del dashboard) y `recovery_email_sent_at`
# (correo de carrito abandonado, una sola vez por carrito).
#
# Las filas existentes toman `updated_at` como alta: es la mejor aproximación
# que hay y evita que todas aparezcan creadas el día del deploy. El UPDATE va
# al final, sin otro ALTER TABLE detrás en la misma transacción.
import django.db.models.functions.datetime
import django.utils.timezone
from django.db import migrations, models


def backfill_created_at(apps, schema_editor):
    Cart = apps.get_model("cart", "Cart")
    Cart.objects.update(created_at=models.F("updated_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("cart", "0003_cart_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="cart",
            name="created_at",
            field=models.DateTimeField(
                db_default=django.db.models.functions.datetime.Now(),
                default=django.utils.timezone.now,
            ),
        ),
        migrations.AddField(
            model_name="cart",
            name="recovery_email_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_created_at, migrations.RunPython.noop),
    ]
