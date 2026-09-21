# Design decision #3 (Stage A): `carts` already exists via
# `scripts/schema.sql`. `SeparateDatabaseAndState` keeps this model in
# Django's migration state without any database operation — `migrate` MUST
# NOT create, alter, or drop this table.
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Cart',
                    fields=[
                        ('id', models.TextField(primary_key=True, serialize=False)),
                        ('data', models.JSONField(default=dict)),
                        ('updated_at', models.DateTimeField()),
                    ],
                    options={
                        'db_table': 'carts',
                        'managed': False,
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
