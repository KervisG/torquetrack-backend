# Stripe se reemplaza por Authorize.net: el id del reembolso deja de ser de
# Stripe. Solo se renombra la columna; los datos existentes se conservan.
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("checkout", "0002_db_on_delete"),
    ]

    operations = [
        migrations.RenameField(
            model_name="refund",
            old_name="stripe_refund_id",
            new_name="provider_refund_id",
        ),
    ]
