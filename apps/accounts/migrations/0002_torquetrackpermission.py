# Design decision #6 (RBAC): `TorqueTrackPermission` is a marker model with
# NO real table (see `apps/accounts/models.py`). `SeparateDatabaseAndState`
# records it in Django's migration state (so ContentType/Permission tooling
# can reference `accounts.torquetrackpermission`) while emitting ZERO
# database operations, matching the Stage A migration style used elsewhere
# in this app for `managed = False` models.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='TorqueTrackPermission',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                    ],
                    options={
                        'verbose_name': 'TorqueTrack permission',
                        'managed': False,
                        'default_permissions': (),
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
