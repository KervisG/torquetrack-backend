"""`calculate_sales_tax` es la única implementación del impuesto de venta: las
demás apps la importan de este paquete."""
from apps.tax.services.sales_tax import (
    FALLBACK_TAX_RATES,
    calculate_sales_tax,
    estimate_tax,
    estimate_tax_for_customer,
    is_tax_exempt,
)

__all__ = [
    "FALLBACK_TAX_RATES",
    "calculate_sales_tax",
    "estimate_tax",
    "estimate_tax_for_customer",
    "is_tax_exempt",
]
