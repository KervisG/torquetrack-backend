# Tabla `roles` y su M2M a `auth.Permission`. Se rehízo desde cero al partir
# la antigua app de cuentas en `authorization` (roles y permisos) y
# `authentication` (cuentas y sesión): exige una base nueva (ver
# `backend/README.md`).
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="Role",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=80, unique=True)),
                ("slug", models.SlugField(unique=True)),
                ("full_access", models.BooleanField(default=False)),
                (
                    "permissions",
                    models.ManyToManyField(
                        blank=True, related_name="staff_roles", to="auth.permission"
                    ),
                ),
            ],
            options={
                "db_table": "roles",
                "ordering": ["name"],
                "permissions": [
                    ("manage_users", "Can manage users"),
                    ("view_dashboard", "Can view dashboard"),
                ],
            },
        ),
    ]
