# Con todas las filas completadas por `0004_product_slug`, el slug pasa a ser
# obligatorio y único.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0004_product_slug"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="slug",
            field=models.SlugField(max_length=120, unique=True),
        ),
    ]
