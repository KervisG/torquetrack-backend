from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("backoffice", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="activitylog",
            options={
                "db_table": "activity_logs",
                "managed": False,
                "permissions": [
                    ("view_dashboard", "Can view dashboard"),
                ],
            },
        ),
    ]
