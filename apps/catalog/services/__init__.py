"""API pública de los services del catálogo. El storefront lee con los
`ReadOnlyModelViewSet` de `views/storefront.py`; las reglas propias son las
del panel (`admin.py`) y el precio de líneas y totales (`pricing.py`), que
usan `checkout` y `quotes`. `export.py` arma el ZIP del catálogo del panel."""
from apps.catalog.services.admin import (
    delete_admin_product,
    list_admin_products,
    product_price_error,
    set_admin_product_active,
    upsert_admin_product,
)
from apps.catalog.services.brands import (
    create_admin_brand,
    ensure_brands,
    list_admin_brands,
    remove_admin_brand_logo,
    set_admin_brand_active,
    set_admin_brand_logo,
)
from apps.catalog.services.categories import (
    create_admin_category,
    ensure_category,
    export_categories,
    import_categories,
    invalid_category_rows,
    list_admin_categories,
    set_admin_category_line,
)
from apps.catalog.services.export import build_catalog_export, export_filename
from apps.catalog.services.fitment import (
    application_codes,
    backfill_product_fitments,
    list_applications,
    serialize_application,
)
from apps.catalog.services.pricing import (
    MAX_STOREFRONT_QUANTITY,
    STOREFRONT_QUANTITY_ERROR,
    InvalidPrice,
    InvalidQuantity,
    PricedLine,
    PricedLines,
    PricingError,
    UnpricedProducts,
    build_totals,
    parse_quantity,
    price_lines,
    serialize_totals,
)

__all__ = [
    "InvalidPrice",
    "InvalidQuantity",
    "MAX_STOREFRONT_QUANTITY",
    "PricedLine",
    "PricedLines",
    "PricingError",
    "STOREFRONT_QUANTITY_ERROR",
    "UnpricedProducts",
    "application_codes",
    "backfill_product_fitments",
    "build_catalog_export",
    "build_totals",
    "create_admin_brand",
    "create_admin_category",
    "delete_admin_product",
    "ensure_brands",
    "ensure_category",
    "export_categories",
    "export_filename",
    "import_categories",
    "invalid_category_rows",
    "list_admin_brands",
    "list_admin_categories",
    "list_admin_products",
    "list_applications",
    "parse_quantity",
    "price_lines",
    "product_price_error",
    "remove_admin_brand_logo",
    "serialize_application",
    "serialize_totals",
    "set_admin_brand_active",
    "set_admin_brand_logo",
    "set_admin_category_line",
    "set_admin_product_active",
    "upsert_admin_product",
]
