from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="product",
            options={
                "db_table": "products",
                "managed": False,
                "permissions": [
                    ("edit_pricing", "Can edit pricing"),
                    ("view_costs", "Can view costs"),
                ],
            },
        ),
    ]
