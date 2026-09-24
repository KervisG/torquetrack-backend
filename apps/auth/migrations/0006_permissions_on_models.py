# Los 26 permisos pasan a los modelos de dominio. Se remapean Role y
# Group, y se retira el marcador TorqueTrackPermission.
from django.db import migrations

# Copia congelada de `permission_catalog`: una migración no debe importar
# código de la app, porque un cambio posterior del catálogo la reescribiría.
STAFF_PERMISSIONS = [
    ("dashboard.view", "tt_auth", "user", "view_dashboard"),
    ("products.view", "catalog", "product", "view_product"),
    ("products.edit", "catalog", "product", "change_product"),
    ("pricing.edit", "catalog", "product", "edit_pricing"),
    ("costs.view", "catalog", "product", "view_costs"),
    ("quotes.view", "quotes", "quote", "view_quote"),
    ("quotes.create", "quotes", "quote", "add_quote"),
    ("quotes.edit", "quotes", "quote", "change_quote"),
    ("quotes.send", "quotes", "quote", "send_quote"),
    ("quotes.convert", "quotes", "quote", "convert_quote"),
    ("quotes.delete", "quotes", "quote", "delete_quote"),
    ("carts.view", "cart", "cart", "view_cart"),
    ("orders.view", "checkout", "order", "view_order"),
    ("orders.status", "checkout", "order", "change_status"),
    ("orders.cancel", "checkout", "order", "cancel_order"),
    ("payments.take", "checkout", "payment", "take_payment"),
    ("payments.refund", "checkout", "payment", "refund_payment"),
    ("payments.transaction_id", "checkout", "payment", "view_transaction_id"),
    ("cores.manage", "checkout", "order", "manage_cores"),
    ("returns.manage", "checkout", "order", "manage_returns"),
    ("customers.view", "customers", "customer", "view_customer"),
    ("customers.edit", "customers", "customer", "change_customer"),
    ("customers.delete", "customers", "customer", "delete_customer"),
    ("tax_exemptions.review", "customers", "customer", "review_tax_exemption"),
    ("activity.view", "audit", "activitylog", "view_activitylog"),
    ("users.manage", "tt_auth", "user", "manage_users"),
]
DEFAULT_EMPLOYEE_PERMISSIONS = [
    "dashboard.view",
    "products.view",
    "quotes.view",
    "quotes.create",
    "quotes.edit",
    "quotes.send",
    "quotes.convert",
    "carts.view",
    "orders.view",
    "orders.status",
    "payments.take",
    "cores.manage",
    "returns.manage",
    "customers.view",
    "customers.edit",
]

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
                [new_by_legacy[legacy] for legacy in DEFAULT_EMPLOYEE_PERMISSIONS]
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
        role.permissions.set(remapped or [new_by_legacy[item] for item in DEFAULT_EMPLOYEE_PERMISSIONS])

    group = Group.objects.filter(name=EMPLOYEE_GROUP).first()
    if group is not None:
        group.permissions.set([new_by_legacy[legacy] for legacy in DEFAULT_EMPLOYEE_PERMISSIONS])

    employee = Role.objects.filter(slug=EMPLOYEE_SLUG, full_access=False).first()
    if employee is not None:
        employee.permissions.set([new_by_legacy[legacy] for legacy in DEFAULT_EMPLOYEE_PERMISSIONS])

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
