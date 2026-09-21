# Design decision #3 (Stage A): `quotes` already exists via
# `scripts/schema.sql`. `SeparateDatabaseAndState` keeps this model in
# Django's migration state without any database operation — `migrate` MUST
# NOT create, alter, or drop this table. The `customer` FK field is
# intentionally absent from this state (Django's autodetector never emits
# relation fields for `managed = False` models); the real
# `apps.quotes.models.Quote` class still exposes it at runtime.
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Quote',
                    fields=[
                        ('id', models.TextField(primary_key=True, serialize=False)),
                        ('number', models.TextField(unique=True)),
                        ('status', models.TextField(default='BUILDING')),
                        ('data', models.JSONField(default=dict)),
                        ('created_at', models.DateTimeField()),
                        ('expires_at', models.DateTimeField(blank=True, null=True)),
                        ('updated_at', models.DateTimeField()),
                    ],
                    options={
                        'db_table': 'quotes',
                        'managed': False,
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
