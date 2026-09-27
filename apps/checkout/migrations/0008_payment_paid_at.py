from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("checkout", "0007_refund_db_on_delete"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="paid_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
