from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="customer",
            options={
                "db_table": "customers",
                "managed": False,
                "permissions": [
                    ("review_tax_exemption", "Can review tax exemptions"),
                ],
            },
        ),
    ]
