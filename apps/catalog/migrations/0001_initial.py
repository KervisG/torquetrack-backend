# Design decision #3 (Stage A): `products` and `applications` already exist
# via `scripts/schema.sql`. `SeparateDatabaseAndState` keeps these models in
# Django's migration state without any database operation — `migrate` MUST
# NOT create, alter, or drop either table.
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Application',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('data', models.JSONField(default=dict)),
                    ],
                    options={
                        'db_table': 'applications',
                        'managed': False,
                    },
                ),
                migrations.CreateModel(
                    name='Product',
                    fields=[
                        ('id', models.TextField(primary_key=True, serialize=False)),
                        ('data', models.JSONField(default=dict)),
                        ('active', models.BooleanField(default=True)),
                        ('updated_at', models.DateTimeField()),
                    ],
                    options={
                        'db_table': 'products',
                        'managed': False,
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
