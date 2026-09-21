# Design decision #3 (Stage A): `activity_logs` already exists via
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
                    name='ActivityLog',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('actor_id', models.TextField(blank=True, null=True)),
                        ('action', models.TextField()),
                        ('entity_type', models.TextField(blank=True, null=True)),
                        ('entity_id', models.TextField(blank=True, null=True)),
                        ('data', models.JSONField(default=dict)),
                        ('created_at', models.DateTimeField()),
                    ],
                    options={
                        'db_table': 'activity_logs',
                        'managed': False,
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
