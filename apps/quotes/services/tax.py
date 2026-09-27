"""Impuesto de una cotización del panel: lo calcula el servidor al guardar.

El editor ya no fija el impuesto. `upsert_admin_quote` lo recalcula con
`estimate_tax_for_customer` sobre las líneas repreciadas y la dirección de
envío que guarda la cotización (`shippingAddress`), así el pedido que sale de
convertirla o de pagarla hereda un impuesto que el staff no pudo bajar. La
única excepción es un override explícito (`taxOverride`), que exige
`tax_exemptions.review` y queda en la bitácora.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal

from apps.common.numbers import ZERO, money, money_decimal
from apps.tax.services import estimate_tax_for_customer, is_tax_exempt

# El mismo permiso que revisa los certificados de exención: quien puede
# eximir a un cliente es quien puede fijar su impuesto a mano.
TAX_OVERRIDE_PERMISSION = "tax_exemptions.review"
TAX_OVERRIDE_FORBIDDEN = "Overriding tax requires tax_exemptions.review"
TAX_ADDRESS_REQUIRED = "Shipping state and ZIP are required to calculate tax"
INVALID_SHIPPING_ADDRESS = "Shipping address must be an object with text fields"
INVALID_SHIPPING_STATE = "Shipping state must be a 2-letter code"
INVALID_SHIPPING_ZIP = "Shipping ZIP must be 5 digits or ZIP+4"
SHIPPING_FIELD_TOO_LONG = "Shipping address fields must be 200 characters or fewer"
INVALID_TAX_OVERRIDE = "Tax override must be an object with amount and reason"
INVALID_TAX_OVERRIDE_AMOUNT = "Tax override amount must be 0 or more"
TAX_OVERRIDE_REASON_REQUIRED = "Tax override reason is required"
TAX_OVERRIDE_REASON_TOO_LONG = "Tax override reason must be 500 characters or fewer"
EXEMPT_TAX_OVERRIDE = "Tax-exempt customers cannot have a tax override"

SHIPPING_ADDRESS_FIELDS = ("address1", "city", "state", "zip")
MAX_ADDRESS_FIELD_LENGTH = 200
MAX_OVERRIDE_REASON_LENGTH = 500
_STATE_CODE = re.compile(r"[A-Z]{2}")
_ZIP_CODE = re.compile(r"\d{5}(-\d{4})?")

# Claves de `Quote.data` que escribe este módulo. El body no puede traerlas:
# se descartan y se vuelven a escribir con lo que decidió el servidor.
QUOTE_TAX_KEYS = (
    "tax",
    "taxExempt",
    "exempt",
    "taxSource",
    "taxRate",
    "taxProvider",
    "taxDescription",
    "taxOverride",
    "shippingAddress",
)


class QuoteTaxError(Exception):
    """Rechazo con el mensaje para el panel; la view lo traduce a `{"error"}`."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class QuoteTax:
    amount: Decimal
    # Lo que se guarda en `Quote.data` junto a los totales.
    fields: dict


def parse_shipping_address(raw) -> dict:
    """Las cuatro claves siempre presentes (vacías si faltan). Un ZIP como
    número perdería los ceros a la izquierda, así que solo se acepta texto."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise QuoteTaxError(INVALID_SHIPPING_ADDRESS)
    address = {}
    for field in SHIPPING_ADDRESS_FIELDS:
        value = raw.get(field)
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise QuoteTaxError(INVALID_SHIPPING_ADDRESS)
        value = value.strip()
        if len(value) > MAX_ADDRESS_FIELD_LENGTH:
            raise QuoteTaxError(SHIPPING_FIELD_TOO_LONG)
        address[field] = value
    address["state"] = address["state"].upper()
    if address["state"] and not _STATE_CODE.fullmatch(address["state"]):
        raise QuoteTaxError(INVALID_SHIPPING_STATE)
    if address["zip"] and not _ZIP_CODE.fullmatch(address["zip"]):
        raise QuoteTaxError(INVALID_SHIPPING_ZIP)
    return address


def _parse_override(raw) -> tuple[Decimal, str]:
    if not isinstance(raw, dict):
        raise QuoteTaxError(INVALID_TAX_OVERRIDE)
    amount = raw.get("amount")
    # `bool` es subclase de `int`: `true` no es un monto.
    if (
        isinstance(amount, bool)
        or not isinstance(amount, int | float)
        or not math.isfinite(amount)
        or amount < 0
    ):
        raise QuoteTaxError(INVALID_TAX_OVERRIDE_AMOUNT)
    reason = raw.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reason:
        raise QuoteTaxError(TAX_OVERRIDE_REASON_REQUIRED)
    if len(reason) > MAX_OVERRIDE_REASON_LENGTH:
        raise QuoteTaxError(TAX_OVERRIDE_REASON_TOO_LONG)
    return money_decimal(amount), reason


def resolve_quote_tax(
    *,
    customer,
    address: dict,
    subtotal: Decimal,
    core: Decimal,
    shipping,
    override,
    can_override: bool,
    actor_email: str,
    now,
) -> QuoteTax:
    """Decide el impuesto que se guarda. El permiso se mira antes que el
    contenido del override: sin `tax_exemptions.review` la respuesta es 403
    aunque el override venga mal formado."""
    exempt = is_tax_exempt(customer)
    if override is not None:
        if not can_override:
            raise QuoteTaxError(TAX_OVERRIDE_FORBIDDEN, status=403)
        if exempt:
            raise QuoteTaxError(EXEMPT_TAX_OVERRIDE)
        amount, reason = _parse_override(override)
        return QuoteTax(
            amount,
            {
                "taxExempt": False,
                "taxSource": "manual",
                "taxRate": None,
                "taxProvider": "manual",
                "taxDescription": "Manual override",
                "taxOverride": {
                    "amount": money(amount),
                    "reason": reason,
                    "by": actor_email,
                    "at": now.isoformat(),
                },
            },
        )

    has_address = bool(address["state"] and address["zip"])
    if not exempt and not has_address:
        taxable = money_decimal(subtotal) + money_decimal(core) + money_decimal(shipping)
        if taxable > 0:
            raise QuoteTaxError(TAX_ADDRESS_REQUIRED)
        # Un borrador sin montos no tiene nada que gravar: se guarda sin
        # dirección y sin llamar a TaxJar.
        return QuoteTax(
            ZERO,
            {
                "taxExempt": False,
                "taxSource": "calculated",
                "taxRate": 0.0,
                "taxProvider": "none",
                "taxDescription": "No taxable amount",
            },
        )

    # Si TaxJar falla, `calculate_sales_tax` cae a la tabla por estado.
    estimate = estimate_tax_for_customer(
        {
            "subtotal": subtotal,
            "coreCharge": core,
            "shipping": shipping,
            "state": address["state"],
            "zip": address["zip"],
            "city": address["city"],
            "address1": address["address1"],
        },
        customer,
    )
    return QuoteTax(
        money_decimal(estimate["tax"]),
        {
            "taxExempt": exempt,
            "taxSource": "exempt" if exempt else "calculated",
            "taxRate": float(estimate["rate"]),
            "taxProvider": estimate["provider"],
            "taxDescription": estimate["source"],
        },
    )


def override_changed(previous: dict, override: dict | None) -> bool:
    """Volver a guardar el mismo override (el editor lo reenvía en cada
    guardado) no deja otra entrada en la bitácora."""
    if override is None:
        return False
    before = previous.get("taxOverride") if previous.get("taxSource") == "manual" else None
    if not isinstance(before, dict):
        return True
    return (before.get("amount"), before.get("reason")) != (override["amount"], override["reason"])
