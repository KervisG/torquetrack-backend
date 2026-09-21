# Design decision #3 (Stage A): this model binds an existing table that
# `scripts/schema.sql` already owns. `SeparateDatabaseAndState` records the
# model in Django's migration state (so `makemigrations`/`sqlmigrate` know
# about it) while emitting ZERO database operations — `migrate` MUST NOT
# create, alter, or drop the `users` table.
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='User',
                    fields=[
                        ('id', models.TextField(primary_key=True, serialize=False)),
                        ('username', models.TextField(unique=True)),
                        ('password_hash', models.TextField()),
                        ('role', models.TextField(default='authorized')),
                        ('active', models.BooleanField(default=True)),
                        ('display_name', models.TextField(blank=True, null=True)),
                        ('permissions', models.JSONField(default=list)),
                        ('created_at', models.DateTimeField()),
                    ],
                    options={
                        'db_table': 'users',
                        'managed': False,
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
