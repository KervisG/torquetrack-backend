# `orders` y `payments` pasan a ser tablas administradas por Django, y se
# agrega `document_sequences` para numerar pedidos y cotizaciones.
#
# El proyecto no está en producción: las tablas heredadas de
# `scripts/schema.sql` se descartan (si existen) y se crean desde el modelo,
# ahora con las FK reales (`orders.customer_id` → `customers`,
# `payments.order_id` → `orders`, ambas on delete set null) y la restricción
# única sobre `orders.number`. El `DeleteModel` de estado conserva los
# `ContentType` y los permisos de pedidos y pagos.
import django.db.models.deletion
import django.db.models.functions.datetime
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("checkout", "0002_order_payment_permissions"),
        ("customers", "0003_managed_customer"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="Payment"),
                migrations.DeleteModel(name="Order"),
            ],
            database_operations=[
                migrations.RunSQL(
                    "DROP TABLE IF EXISTS payments CASCADE;"
                    " DROP TABLE IF EXISTS orders CASCADE",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.TextField(primary_key=True, serialize=False)),
                ("number", models.TextField(unique=True)),
                ("status", models.TextField(db_default="OPEN", default="OPEN")),
                ("payment_status", models.TextField(db_default="UNPAID", default="UNPAID")),
                ("data", models.JSONField(default=dict)),
                (
                    "created_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="orders",
                        to="customers.customer",
                    ),
                ),
            ],
            options={
                "db_table": "orders",
                "permissions": [
                    ("change_status", "Can change order status"),
                    ("cancel_order", "Can cancel orders"),
                    ("manage_cores", "Can manage cores"),
                    ("manage_returns", "Can manage returns"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.TextField(primary_key=True, serialize=False)),
                ("provider", models.TextField()),
                ("provider_id", models.TextField(blank=True, null=True)),
                ("status", models.TextField()),
                (
                    "amount",
                    models.DecimalField(
                        db_default=0, decimal_places=2, default=0, max_digits=12
                    ),
                ),
                ("data", models.JSONField(db_default={}, default=dict)),
                (
                    "created_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payments",
                        to="checkout.order",
                    ),
                ),
            ],
            options={
                "db_table": "payments",
                "permissions": [
                    ("take_payment", "Can take payments"),
                    ("refund_payment", "Can refund payments"),
                    ("view_transaction_id", "Can view payment transaction IDs"),
                ],
            },
        ),
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
    ]
