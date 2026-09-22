from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("checkout", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="order",
            options={
                "db_table": "orders",
                "managed": False,
                "permissions": [
                    ("change_status", "Can change order status"),
                    ("cancel_order", "Can cancel orders"),
                    ("manage_cores", "Can manage cores"),
                    ("manage_returns", "Can manage returns"),
                ],
            },
        ),
        migrations.AlterModelOptions(
            name="payment",
            options={
                "db_table": "payments",
                "managed": False,
                "permissions": [
                    ("take_payment", "Can take payments"),
                    ("refund_payment", "Can refund payments"),
                    ("view_transaction_id", "Can view payment transaction IDs"),
                ],
            },
        ),
    ]
