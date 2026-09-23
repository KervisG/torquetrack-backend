"""Cálculo del impuesto de venta y reglas de `POST tax/estimate`.

`calculate_sales_tax` es la única implementación del cálculo; el checkout la
importa de aquí. La llamada HTTP a TaxJar vive en el adaptador
`apps.integrations.tax.taxjar`, pero la política fiscal es de este dominio:
la tabla estática de respaldo por estado, llamar a TaxJar solo con zip de
destino y, si TaxJar falla o no está configurado, estimar con la tabla en
lugar de cortar la compra.

La exención de `estimate_tax` sale solo de la sesión (`linked_customer`, la
misma resolución que usa el checkout). El body nunca elige cliente: con un
`customerId` cualquiera podría pedir una estimación exenta ajena y enterarse
del estado fiscal de ese cliente.
"""
from __future__ import annotations

from django.conf import settings

from apps.checkout.services import linked_customer, money
from apps.integrations.exceptions import ProviderError
from apps.integrations.tax import taxjar

# Tasas estáticas de respaldo cuando TaxJar no está disponible (19 estados).
FALLBACK_TAX_RATES = {
    "FL": 0.06, "GA": 0.04, "TX": 0.0625, "CA": 0.0725, "NY": 0.04,
    "NJ": 0.06625, "PA": 0.06, "IL": 0.0625, "NC": 0.0475, "SC": 0.06,
    "VA": 0.053, "OH": 0.0575, "MI": 0.06, "AZ": 0.056, "CO": 0.029,
    "WA": 0.065, "NV": 0.0685, "TN": 0.07, "AL": 0.04,
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
    """Impuesto de venta del destino: TaxJar cuando hay zip de destino y
    responde; si no, la tabla estática de respaldo."""
    subtotal = money(subtotal)
    core_charge = money(core_charge)
    shipping = money(shipping)
    taxable_amount = money(subtotal + core_charge)
    state = str(state or "").strip().upper()
    zip_code = str(zip_code or "").strip()

    if zip_code:
        try:
            quote = taxjar.calculate_tax(
                from_zip=settings.SHIP_FROM_ZIP or "34241",
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
                "tax": money(quote["amount_to_collect"]),
                "rate": quote["rate"],
                "source": "TaxJar destination tax",
                "provider": "taxjar",
                "estimated": False,
            }

    rate = FALLBACK_TAX_RATES.get(state, 0)
    return {
        "tax": money((taxable_amount + shipping) * rate),
        "rate": rate,
        "source": "Estimated state tax - TaxJar unavailable",
        "provider": "fallback",
        "estimated": True,
    }


def _coalesce(payload: dict, *keys: str, default=0):
    """Mirror JS `??` (nullish coalescing): only fall through on a missing
    key or an explicit `None`, never on another falsy value like `0`."""
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def estimate_tax(payload: dict, user) -> dict:
    """Estimación para el checkout del storefront. Normaliza los alias del
    endpoint público (`amount`/`subtotal`, `core`/`coreCharge` y los
    respaldos `address.{state,zip,city,address1}`)."""
    profile = linked_customer(user)
    if profile is not None and profile.tax_status == "VERIFIED":
        return dict(EXEMPT_ESTIMATE)

    address = payload.get("address") or {}
    return calculate_sales_tax(
        subtotal=_coalesce(payload, "subtotal", "amount"),
        core_charge=_coalesce(payload, "coreCharge", "core"),
        shipping=_coalesce(payload, "shipping"),
        state=payload.get("state") or address.get("state"),
        zip_code=payload.get("zip") or address.get("zip"),
        city=payload.get("city") or address.get("city"),
        address1=payload.get("address1") or address.get("address1"),
    )
