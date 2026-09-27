# El carrito de una cuenta cuelga de `user`: un solo carrito por cuenta.
#
# Django 5.2 crea la FK como NO ACTION y aplica CASCADE solo desde el ORM; el
# `RunSQL` lleva el CASCADE también a Postgres (ver `checkout/0005_db_on_delete`
# y `backend/tests/test_db_on_delete.py`).
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

FOREIGN_KEY = "carts_user_id_3a9d1785_fk_users_id"


def _recreate(on_delete):
    return (
        f"ALTER TABLE carts DROP CONSTRAINT {FOREIGN_KEY},"
        f" ADD CONSTRAINT {FOREIGN_KEY} FOREIGN KEY (user_id) REFERENCES users(id)"
        f"{on_delete} DEFERRABLE INITIALLY DEFERRED"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("cart", "0002_managed_cart"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="cart",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="carts",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="cart",
            constraint=models.UniqueConstraint(fields=("user",), name="carts_one_per_user"),
        ),
        migrations.RunSQL(_recreate(" ON DELETE CASCADE"), reverse_sql=_recreate("")),
    ]
