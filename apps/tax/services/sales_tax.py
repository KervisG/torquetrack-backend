"""Impuesto de venta: la única implementación del cálculo, que también usa el checkout."""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from apps.common.numbers import ZERO, money, money_decimal
from apps.common.us_addresses import (
    normalize_state_code,
    shipping_state_error,
    shipping_zip_error,
)
from apps.customers.models import TaxStatus
from apps.customers.services import customer_for_user
from apps.integrations.exceptions import ProviderError
from apps.integrations.tax import taxjar

# Tasa de respaldo cuando TaxJar no está disponible: solo la estatal de FL,
# el único estado con nexo. El recargo discrecional del condado no se estima
# aquí; lo calcula TaxJar. En `Decimal`: con `float`, 9.25 × 0.06 da
# 0.55499... y se cobraba un centavo de menos.
FALLBACK_TAX_RATES = {"FL": Decimal("0.06")}

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
    """Única puerta del impuesto: storefront, checkout y cotizaciones pasan por
    aquí, así el nexo (`SALES_TAX_NEXUS_STATES`) se aplica en un solo lugar.
    `tax` y `rate` salen en `Decimal`; quien responde JSON los serializa."""
    shipping = money_decimal(shipping)
    taxable_amount = money_decimal(money_decimal(subtotal) + money_decimal(core_charge))
    state = str(state or "").strip().upper()
    zip_code = str(zip_code or "").strip()

    if state not in settings.SALES_TAX_NEXUS_STATES:
        return {
            "tax": ZERO,
            "rate": ZERO,
            "source": "No sales tax nexus in destination state",
            "provider": "none",
            "estimated": False,
        }

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
    # Florida grava el envío cuando el comprador no puede evitarlo (regla
    # 12A-1.045), y el checkout siempre exige un método de envío.
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
    el cliente de la cotización, nunca con el perfil del empleado.

    Sin exención el estado es obligatorio, igual que en el checkout: un 0 por
    falta de estado se leería como "sin impuesto" aunque el envío vaya a FL."""
    customer = customer_for_user(user)
    if not is_tax_exempt(customer):
        address = payload.get("address") if isinstance(payload.get("address"), dict) else {}
        state = payload.get("state") or address.get("state")
        state_error = shipping_state_error(state)
        if state_error:
            return {"error": state_error, "status": 400}
        state = normalize_state_code(state)
        # El ZIP es opcional en la estimación (sin él se usa la tabla por
        # estado), pero si viene tiene que ser del estado.
        zip_code = payload.get("zip") or address.get("zip")
        if zip_code:
            zip_code = zip_code.strip() if isinstance(zip_code, str) else zip_code
            zip_error = shipping_zip_error(zip_code, state)
            if zip_error:
                return {"error": zip_error, "status": 400}
        payload = {**payload, "state": state}
    return estimate_tax_for_customer(payload, customer)
