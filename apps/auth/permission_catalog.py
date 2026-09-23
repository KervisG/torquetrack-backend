"""`legacy` es el código con punto (`dashboard.view`) que usan el panel y el
jsonb; `app_label` + `codename` es el `Permission` de Django."""

# (legacy, app_label, model, codename)
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

DEFAULT_ROLE_LEGACY = [
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

LEGACY_TO_DJANGO = {
    legacy: (app_label, codename) for legacy, app_label, _model, codename in STAFF_PERMISSIONS
}

DJANGO_TO_LEGACY = {
    (app_label, codename): legacy
    for legacy, app_label, _model, codename in STAFF_PERMISSIONS
}


def resolve_staff_permission(permission: str) -> tuple[str, str] | None:
    mapped = LEGACY_TO_DJANGO.get(permission)
    if mapped is not None:
        return mapped
    if "." not in permission:
        return None
    app_label, codename = permission.split(".", 1)
    if (app_label, codename) in DJANGO_TO_LEGACY:
        return app_label, codename
    return None
