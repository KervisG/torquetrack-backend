"""API pública de los services del catálogo. El storefront lee con los
`ReadOnlyModelViewSet` de `views/storefront.py`, así que solo el panel tiene
reglas propias."""
from apps.catalog.services.admin import (
    COST_FIELDS,
    HIDDEN_WITHOUT_COSTS,
    PRICE_FIELDS,
    PROTECTED_FIELDS,
    deactivate_admin_product,
    list_admin_products,
    product_price_error,
    serialize_admin_product,
    upsert_admin_product,
)

__all__ = [
    "COST_FIELDS",
    "HIDDEN_WITHOUT_COSTS",
    "PRICE_FIELDS",
    "PROTECTED_FIELDS",
    "deactivate_admin_product",
    "list_admin_products",
    "product_price_error",
    "serialize_admin_product",
    "upsert_admin_product",
]
