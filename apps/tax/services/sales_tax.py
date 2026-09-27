"""Impuesto de venta: la única implementación del cálculo, que también usa el checkout."""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from apps.common.numbers import ZERO, money, money_decimal
from apps.customers.models import TaxStatus
from apps.customers.services import customer_for_user
from apps.integrations.exceptions import ProviderError
from apps.integrations.tax import taxjar

# Tasas de respaldo cuando TaxJar no está disponible. En `Decimal`: con
# `float`, 9.25 × 0.06 da 0.55499... y se cobraba un centavo de menos.
FALLBACK_TAX_RATES = {
    state: Decimal(rate)
    for state, rate in {
        "FL": "0.06", "GA": "0.04", "TX": "0.0625", "CA": "0.0725", "NY": "0.04",
        "NJ": "0.06625", "PA": "0.06", "IL": "0.0625", "NC": "0.0475", "SC": "0.06",
        "VA": "0.053", "OH": "0.0575", "MI": "0.06", "AZ": "0.056", "CO": "0.029",
        "WA": "0.065", "NV": "0.0685", "TN": "0.07", "AL": "0.04",
    }.items()
}

EXEMPT_ESTIMATE = {
    "tax": 0,
    "rate": 0,
    "source": "Tax exempt - certificate verified",
    "exempt": True,
    "provider": "exempt",
}


def calculate_sales_tax(
    *, subtotal, core_charge, shipping, state, zip_code, city=None, address1=None
) -> dict:
    """`tax` y `rate` salen en `Decimal`; quien responde JSON los serializa."""
    shipping = money_decimal(shipping)
    taxable_amount = money_decimal(money_decimal(subtotal) + money_decimal(core_charge))
    state = str(state or "").strip().upper()
    zip_code = str(zip_code or "").strip()

    if zip_code:
        try:
            quote = taxjar.calculate_tax(
                from_zip=settings.SHIP_FROM_ZIP,
                to_state=state,
                to_zip=zip_code,
                to_city=city,
                to_street=address1,
                amount=taxable_amount,
                shipping=shipping,
            )
        except ProviderError:
            # Sin key o con TaxJar caído se estima con la tabla: un impuesto
            # aproximado no debe bloquear el checkout.
            pass
        else:
            return {
                "tax": money_decimal(quote["amount_to_collect"]),
                "rate": Decimal(str(quote["rate"])),
                "source": "TaxJar destination tax",
                "provider": "taxjar",
                "estimated": False,
            }

    rate = FALLBACK_TAX_RATES.get(state, ZERO)
    return {
        "tax": money_decimal((taxable_amount + shipping) * rate),
        "rate": rate,
        "source": "Estimated state tax - TaxJar unavailable",
        "provider": "fallback",
        "estimated": True,
    }


def _coalesce(payload: dict, *keys: str, default=0):
    """Solo pasa a la siguiente clave si falta o es `None`: un `0` explícito se respeta."""
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def is_tax_exempt(customer) -> bool:
    """Única regla de exención: solo un certificado revisado por el staff
    (`VERIFIED`) exime; un perfil pendiente o rechazado paga impuesto."""
    return customer is not None and customer.tax_status == TaxStatus.VERIFIED


def estimate_tax_for_customer(payload: dict, customer) -> dict:
    """Estimación para un `Customer` que ya resolvió quien llama. El body nunca
    decide la exención: solo el perfil que se recibe (o `None`, sin perfil)."""
    if is_tax_exempt(customer):
        return dict(EXEMPT_ESTIMATE)

    address = payload.get("address") or {}
    result = calculate_sales_tax(
        subtotal=_coalesce(payload, "subtotal", "amount"),
        core_charge=_coalesce(payload, "coreCharge", "core"),
        shipping=_coalesce(payload, "shipping"),
        state=payload.get("state") or address.get("state"),
        zip_code=payload.get("zip") or address.get("zip"),
        city=payload.get("city") or address.get("city"),
        address1=payload.get("address1") or address.get("address1"),
    )
    return {**result, "tax": money(result["tax"]), "rate": float(result["rate"])}


def estimate_tax(payload: dict, user) -> dict:
    """Storefront: la exención sale solo de la sesión. Con un `customerId` en
    el body cualquiera podría pedir una estimación exenta ajena y enterarse del
    estado fiscal de ese cliente. El panel usa `estimate_tax_for_customer` con
    el cliente de la cotización, nunca con el perfil del empleado."""
    return estimate_tax_for_customer(payload, customer_for_user(user))
