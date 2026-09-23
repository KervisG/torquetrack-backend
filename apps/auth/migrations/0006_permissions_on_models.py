# Los 26 permisos pasan a los modelos de dominio. Se remapean Role y
# Group, y se retira el marcador TorqueTrackPermission.
from django.db import migrations

from apps.auth.permission_catalog import DEFAULT_ROLE_LEGACY, STAFF_PERMISSIONS

OLD_CONTENT_TYPE = ("tt_auth", "torquetrackpermission")
EMPLOYEE_GROUP = "employee_default"
EMPLOYEE_SLUG = "employee"


def _old_codename(legacy: str) -> str:
    return legacy.replace(".", "_")


def remap_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Group = apps.get_model("auth", "Group")
    Role = apps.get_model("tt_auth", "Role")

    new_by_legacy = {}
    for legacy, app_label, model, codename in STAFF_PERMISSIONS:
        content_type, _ = ContentType.objects.get_or_create(
            app_label=app_label, model=model
        )
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": legacy},
        )
        new_by_legacy[legacy] = permission

    for role in Role.objects.all():
        if role.full_access:
            role.permissions.clear()
            continue
        current = list(role.permissions.all())
        if not current:
            role.permissions.set(
                [new_by_legacy[legacy] for legacy in DEFAULT_ROLE_LEGACY]
            )
            continue
        remapped = []
        for old in current:
            legacy = next(
                (item for item, *_rest in STAFF_PERMISSIONS if _old_codename(item) == old.codename),
                None,
            )
            if legacy is not None:
                remapped.append(new_by_legacy[legacy])
        role.permissions.set(remapped or [new_by_legacy[item] for item in DEFAULT_ROLE_LEGACY])

    group = Group.objects.filter(name=EMPLOYEE_GROUP).first()
    if group is not None:
        group.permissions.set([new_by_legacy[legacy] for legacy in DEFAULT_ROLE_LEGACY])

    employee = Role.objects.filter(slug=EMPLOYEE_SLUG, full_access=False).first()
    if employee is not None:
        employee.permissions.set([new_by_legacy[legacy] for legacy in DEFAULT_ROLE_LEGACY])

    Permission.objects.filter(
        content_type__app_label=OLD_CONTENT_TYPE[0],
        content_type__model=OLD_CONTENT_TYPE[1],
    ).delete()
    ContentType.objects.filter(
        app_label=OLD_CONTENT_TYPE[0], model=OLD_CONTENT_TYPE[1]
    ).delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tt_auth", "0005_user_names"),
        ("catalog", "0002_product_permissions"),
        ("quotes", "0002_quote_permissions"),
        ("checkout", "0002_order_payment_permissions"),
        ("customers", "0002_customer_permissions"),
        ("cart", "0001_initial"),
        ("auth", "0001_initial"),
        ("contenttypes", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "db_table": "users",
                "managed": False,
                "default_permissions": (),
                "permissions": [("manage_users", "Can manage users")],
            },
        ),
        migrations.RunPython(remap_permissions, noop_reverse),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="TorqueTrackPermission"),
            ],
            database_operations=[],
        ),
    ]
