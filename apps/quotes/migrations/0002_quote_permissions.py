from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("quotes", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="quote",
            options={
                "db_table": "quotes",
                "managed": False,
                "permissions": [
                    ("send_quote", "Can send quotes"),
                    ("convert_quote", "Can convert quotes"),
                ],
            },
        ),
    ]
