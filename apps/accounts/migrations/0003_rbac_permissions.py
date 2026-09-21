# Design decision #6 (RBAC, task 3.3): map the 26 permission strings from
# `lib/permissions.ts` `PERMISSIONS` 1:1 onto Django `Permission` codenames
# (dots -> underscores, e.g. `products.edit` -> `products_edit`), anchored
# on the `accounts.torquetrackpermission` ContentType (see
# `0002_torquetrackpermission.py`), plus an `employee_default` Group
# holding exactly the 15 strings from `DEFAULT_EMPLOYEE_PERMISSIONS`.
#
# Both lists were read directly from `lib/permissions.ts` in this session
# (not from the design doc's paraphrase) to guarantee the 1:1 mapping.
from django.db import migrations

CONTENT_TYPE_APP_LABEL = "accounts"
CONTENT_TYPE_MODEL = "torquetrackpermission"
DEFAULT_GROUP_NAME = "employee_default"

# (codename, human-readable name) — codename = permission string with
# "." replaced by "_"; name is a short admin-UI label, not from the source.
PERMISSION_CODENAMES = [
    ("dashboard_view", "Can view dashboard"),
    ("products_view", "Can view products"),
    ("products_edit", "Can edit products"),
    ("pricing_edit", "Can edit pricing"),
    ("costs_view", "Can view costs"),
    ("quotes_view", "Can view quotes"),
    ("quotes_create", "Can create quotes"),
    ("quotes_edit", "Can edit quotes"),
    ("quotes_send", "Can send quotes"),
    ("quotes_convert", "Can convert quotes"),
    ("quotes_delete", "Can delete quotes"),
    ("carts_view", "Can view carts"),
    ("orders_view", "Can view orders"),
    ("orders_status", "Can change order status"),
    ("orders_cancel", "Can cancel orders"),
    ("payments_take", "Can take payments"),
    ("payments_refund", "Can refund payments"),
    ("payments_transaction_id", "Can view payment transaction IDs"),
    ("cores_manage", "Can manage cores"),
    ("returns_manage", "Can manage returns"),
    ("customers_view", "Can view customers"),
    ("customers_edit", "Can edit customers"),
    ("customers_delete", "Can delete customers"),
    ("tax_exemptions_review", "Can review tax exemptions"),
    ("activity_view", "Can view activity log"),
    ("users_manage", "Can manage users"),
]

assert len(PERMISSION_CODENAMES) == 26

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

assert len(DEFAULT_EMPLOYEE_CODENAMES) == 15


def create_permissions_and_default_group(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Group = apps.get_model("auth", "Group")

    content_type, _ = ContentType.objects.get_or_create(
        app_label=CONTENT_TYPE_APP_LABEL, model=CONTENT_TYPE_MODEL
    )

    permissions_by_codename = {}
    for codename, name in PERMISSION_CODENAMES:
        permission, _ = Permission.objects.get_or_create(
            codename=codename,
            content_type=content_type,
            defaults={"name": name},
        )
        permissions_by_codename[codename] = permission

    group, _ = Group.objects.get_or_create(name=DEFAULT_GROUP_NAME)
    group.permissions.set(
        [permissions_by_codename[codename] for codename in DEFAULT_EMPLOYEE_CODENAMES]
    )


def remove_permissions_and_default_group(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Group = apps.get_model("auth", "Group")

    Group.objects.filter(name=DEFAULT_GROUP_NAME).delete()
    codenames = [codename for codename, _ in PERMISSION_CODENAMES]
    Permission.objects.filter(
        codename__in=codenames,
        content_type__app_label=CONTENT_TYPE_APP_LABEL,
        content_type__model=CONTENT_TYPE_MODEL,
    ).delete()
    ContentType.objects.filter(
        app_label=CONTENT_TYPE_APP_LABEL, model=CONTENT_TYPE_MODEL
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_torquetrackpermission"),
        ("auth", "0001_initial"),
        ("contenttypes", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_permissions_and_default_group,
            remove_permissions_and_default_group,
        ),
    ]
