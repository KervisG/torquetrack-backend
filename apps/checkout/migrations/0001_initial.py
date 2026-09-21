# Design decision #3 (Stage A): `orders` and `payments` already exist via
# `scripts/schema.sql`. `SeparateDatabaseAndState` keeps these models in
# Django's migration state without any database operation — `migrate` MUST
# NOT create, alter, or drop either table. The `customer`/`order` FK fields
# are intentionally absent from this state (Django's autodetector never
# emits relation fields for `managed = False` models, since no FK
# constraint is ever created at the database level); the real
# `apps.checkout.models` classes still expose them at runtime.
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Order',
                    fields=[
                        ('id', models.TextField(primary_key=True, serialize=False)),
                        ('number', models.TextField(unique=True)),
                        ('status', models.TextField(default='OPEN')),
                        ('payment_status', models.TextField(default='UNPAID')),
                        ('data', models.JSONField(default=dict)),
                        ('created_at', models.DateTimeField()),
                        ('updated_at', models.DateTimeField()),
                    ],
                    options={
                        'db_table': 'orders',
                        'managed': False,
                    },
                ),
                migrations.CreateModel(
                    name='Payment',
                    fields=[
                        ('id', models.TextField(primary_key=True, serialize=False)),
                        ('provider', models.TextField()),
                        ('provider_id', models.TextField(blank=True, null=True)),
                        ('status', models.TextField()),
                        ('amount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                        ('data', models.JSONField(default=dict)),
                        ('created_at', models.DateTimeField()),
                        ('updated_at', models.DateTimeField()),
                    ],
                    options={
                        'db_table': 'payments',
                        'managed': False,
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
