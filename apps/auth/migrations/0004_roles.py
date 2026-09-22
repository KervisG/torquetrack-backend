# Tablas nuevas `roles` y `employee_roles`. Siembra Admin (acceso total)
# y Employee (los 15 permisos por defecto).
from django.db import migrations, models


ADMIN_SLUG = "admin"
EMPLOYEE_SLUG = "employee"
CONTENT_TYPE_APP_LABEL = "tt_auth"
CONTENT_TYPE_MODEL = "torquetrackpermission"

DEFAULT_EMPLOYEE_CODENAMES = [
    "dashboard_view",
    "products_view",
    "quotes_view",
    "quotes_create",
    "quotes_edit",
    "quotes_send",
    "quotes_convert",
    "carts_view",
    "orders_view",
    "orders_status",
    "payments_take",
    "cores_manage",
    "returns_manage",
    "customers_view",
    "customers_edit",
]


def seed_default_roles(apps, schema_editor):
    Role = apps.get_model("tt_auth", "Role")
    Permission = apps.get_model("auth", "Permission")

    admin_role, _ = Role.objects.get_or_create(
        slug=ADMIN_SLUG,
        defaults={"name": "Admin", "full_access": True},
    )
    admin_role.full_access = True
    admin_role.name = admin_role.name or "Admin"
    admin_role.save()

    employee_role, _ = Role.objects.get_or_create(
        slug=EMPLOYEE_SLUG,
        defaults={"name": "Employee", "full_access": False},
    )
    permissions = list(
        Permission.objects.filter(
            content_type__app_label=CONTENT_TYPE_APP_LABEL,
            content_type__model=CONTENT_TYPE_MODEL,
            codename__in=DEFAULT_EMPLOYEE_CODENAMES,
        )
    )
    employee_role.permissions.set(permissions)


def unseed_default_roles(apps, schema_editor):
    Role = apps.get_model("tt_auth", "Role")
    EmployeeRole = apps.get_model("tt_auth", "EmployeeRole")
    EmployeeRole.objects.filter(role__slug__in=[ADMIN_SLUG, EMPLOYEE_SLUG]).delete()
    Role.objects.filter(slug__in=[ADMIN_SLUG, EMPLOYEE_SLUG]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tt_auth", "0003_rbac_permissions"),
        ("auth", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Role",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=80, unique=True)),
                ("slug", models.SlugField(unique=True)),
                ("full_access", models.BooleanField(default=False)),
                (
                    "permissions",
                    models.ManyToManyField(
                        blank=True,
                        related_name="staff_roles",
                        to="auth.permission",
                    ),
                ),
            ],
            options={
                "db_table": "roles",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="EmployeeRole",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("user_id", models.TextField(unique=True)),
                (
                    "role",
                    models.ForeignKey(
                        on_delete=models.PROTECT,
                        related_name="assignments",
                        to="tt_auth.role",
                    ),
                ),
            ],
            options={
                "db_table": "employee_roles",
            },
        ),
        migrations.RunPython(seed_default_roles, unseed_default_roles),
    ]
