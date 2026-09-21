"""`POST tax/estimate` business rules (task 7.5), pinned against
`app/api/tax/estimate/route.ts` and `lib/tax.ts`.

`app/api/tax/estimate/route.ts` first checks `customerId` -> `tax_status`
directly (not delegated to `lib/tax.ts`), then calls `calculateSalesTax`
otherwise. The calculation itself (TaxJar REST call + the ~19-state static
fallback table) is NOT duplicated here — it reuses
`apps.checkout.services.calculate_sales_tax`, the same near-verbatim port of
`lib/tax.ts` that Phase 5's checkout repricing already uses (design decision
#7's precedent: one shared implementation, not a second copy under
`apps/tax/`). Only the flexible input-field aliasing that `lib/tax.ts`'s
public-facing `calculateSalesTax(input:any)` supports (`amount`/`subtotal`,
`core`/`coreCharge`, and `address.{state,zip,city,address1}` fallbacks) is
normalized here before delegating, since `calculate_sales_tax`'s internal
checkout-facing signature expects already-resolved keyword arguments.
"""
from __future__ import annotations

from apps.checkout.services import calculate_sales_tax
from apps.customers.models import Customer


def _coalesce(payload: dict, *keys: str, default=0):
    """Mirror JS `??` (nullish coalescing): only fall through on a missing
    key or an explicit `None`, never on another falsy value like `0`."""
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def estimate_tax(payload: dict) -> dict:
    customer_id = payload.get("customerId")
    if customer_id:
        tax_status = (
            Customer.objects.filter(pk=customer_id).values_list("tax_status", flat=True).first()
        )
        if tax_status == "VERIFIED":
            return {
                "tax": 0,
                "rate": 0,
                "source": "Tax exempt - certificate verified",
                "exempt": True,
                "provider": "exempt",
            }

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
