# Design decision #3 (Stage A): `customers` already exists via
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
                    name='Customer',
                    fields=[
                        ('id', models.TextField(primary_key=True, serialize=False)),
                        ('email', models.TextField(blank=True, null=True, unique=True)),
                        ('password_hash', models.TextField(blank=True, null=True)),
                        ('data', models.JSONField(default=dict)),
                        ('portal_status', models.TextField(default='NOT ACTIVATED')),
                        ('activation_token_hash', models.TextField(blank=True, null=True)),
                        ('activation_expires_at', models.DateTimeField(blank=True, null=True)),
                        ('tax_status', models.TextField(default='NOT SUBMITTED')),
                        ('created_at', models.DateTimeField()),
                        ('updated_at', models.DateTimeField()),
                    ],
                    options={
                        'db_table': 'customers',
                        'managed': False,
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
