# Siembra los permisos del panel y los dos Roles de partida: `admin` (acceso
# total) y `employee` (los 15 permisos por defecto).
#
# Django crea los `Permission` en `post_migrate`, después de todas las
# migraciones, así que aquí se crean con `get_or_create` (mismo ContentType y
# codename que usará Django, que después no los duplica). No hace falta
# depender de las migraciones de cada app de dominio: el ContentType es solo
# `(app_label, model)`.
from django.db import migrations

# Copia congelada del catálogo de `apps.authorization.permissions`: una
# migración no importa código de la app, porque un cambio posterior del
# catálogo la reescribiría. (code, app_label, model, codename, name)
STAFF_PERMISSIONS = [
    ("dashboard.view", "authorization", "role", "view_dashboard", "Can view dashboard"),
    ("products.view", "catalog", "product", "view_product", "Can view product"),
    ("products.edit", "catalog", "product", "change_product", "Can change product"),
    ("pricing.edit", "catalog", "product", "edit_pricing", "Can edit pricing"),
    ("costs.view", "catalog", "product", "view_costs", "Can view costs"),
    ("quotes.view", "quotes", "quote", "view_quote", "Can view quote"),
    ("quotes.create", "quotes", "quote", "add_quote", "Can add quote"),
    ("quotes.edit", "quotes", "quote", "change_quote", "Can change quote"),
    ("quotes.send", "quotes", "quote", "send_quote", "Can send quotes"),
    ("quotes.convert", "quotes", "quote", "convert_quote", "Can convert quotes"),
    ("quotes.delete", "quotes", "quote", "delete_quote", "Can delete quote"),
    ("carts.view", "cart", "cart", "view_cart", "Can view cart"),
    ("orders.view", "checkout", "order", "view_order", "Can view order"),
    ("orders.status", "checkout", "order", "change_status", "Can change order status"),
    ("orders.cancel", "checkout", "order", "cancel_order", "Can cancel orders"),
    ("payments.take", "checkout", "payment", "take_payment", "Can take payments"),
    ("payments.refund", "checkout", "payment", "refund_payment", "Can refund payments"),
    (
        "payments.transaction_id",
        "checkout",
        "payment",
        "view_transaction_id",
        "Can view payment transaction IDs",
    ),
    ("cores.manage", "checkout", "order", "manage_cores", "Can manage cores"),
    ("returns.manage", "checkout", "order", "manage_returns", "Can manage returns"),
    ("customers.view", "customers", "customer", "view_customer", "Can view customer"),
    ("customers.edit", "customers", "customer", "change_customer", "Can change customer"),
    ("customers.delete", "customers", "customer", "delete_customer", "Can delete customer"),
    (
        "tax_exemptions.review",
        "customers",
        "customer",
        "review_tax_exemption",
        "Can review tax exemptions",
    ),
    ("activity.view", "audit", "activitylog", "view_activitylog", "Can view activity log"),
    ("users.manage", "authorization", "role", "manage_users", "Can manage users"),
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

ADMIN_SLUG = "admin"
EMPLOYEE_SLUG = "employee"


def seed_roles(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Role = apps.get_model("authorization", "Role")

    by_code = {}
    for code, app_label, model, codename, name in STAFF_PERMISSIONS:
        content_type, _ = ContentType.objects.get_or_create(app_label=app_label, model=model)
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type, codename=codename, defaults={"name": name}
        )
        by_code[code] = permission

    # El acceso total no guarda permisos: los concede todos, también los
    # que se agreguen después.
    Role.objects.get_or_create(slug=ADMIN_SLUG, defaults={"name": "Admin", "full_access": True})
    employee, _ = Role.objects.get_or_create(
        slug=EMPLOYEE_SLUG, defaults={"name": "Employee", "full_access": False}
    )
    employee.permissions.set([by_code[code] for code in DEFAULT_EMPLOYEE_PERMISSIONS])


def unseed_roles(apps, schema_editor):
    Role = apps.get_model("authorization", "Role")
    Role.objects.filter(slug__in=[ADMIN_SLUG, EMPLOYEE_SLUG]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(seed_roles, unseed_roles),
    ]
