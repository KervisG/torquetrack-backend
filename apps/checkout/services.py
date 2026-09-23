"""Checkout repricing, Stripe Checkout Session creation, and payment-method
lookup helpers for tasks 5.2/5.3 (spec domain `commerce-checkout`; design
decision #7).

Near-verbatim port of `app/api/checkout/route.ts`, `lib/stripe.ts`, and
`lib/tax.ts` (all re-read directly from source this run, not from the
design doc's paraphrase). `calculate_sales_tax` is scoped to checkout's own
server-side repricing need (task 5.2: "VERIFIED exemption -> $0 tax", which
requires the real calculation for the non-exempt branch); the public
`tax/estimate` HTTP endpoint that also uses this logic in the legacy app is
explicitly Phase 7 scope per the tasks artifact and is NOT implemented
here — this module creates nothing under `apps/tax/`.

Stripe Checkout Session creation uses the official `stripe` Python SDK
(design decision #7), matching `lib/stripe.ts`'s hand-rolled form-encoded
`fetch` call field-for-field (same `mode`, `client_reference_id`,
`success_url`/`cancel_url` templates, `metadata`, and per-line-item
`price_data`/`quantity` shape), not a hand-rolled HTTP call.
"""
from __future__ import annotations

import secrets
from urllib.parse import quote

import requests
import stripe
from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.customers.models import Customer

# Mirrors `lib/tax.ts`'s `fallbackRates` table verbatim (19 states).
FALLBACK_TAX_RATES = {
    "FL": 0.06, "GA": 0.04, "TX": 0.0625, "CA": 0.0725, "NY": 0.04,
    "NJ": 0.06625, "PA": 0.06, "IL": 0.0625, "NC": 0.0475, "SC": 0.06,
    "VA": 0.053, "OH": 0.0575, "MI": 0.06, "AZ": 0.056, "CO": 0.029,
    "WA": 0.065, "NV": 0.0685, "TN": 0.07, "AL": 0.04,
}


def js_number_or(raw, fallback=0.0):
    """Mirror JS `Number(raw || fallback)`: falsy `raw` (None/0/""/False)
    uses `fallback`; otherwise coerce `raw` to a number."""
    if raw in (None, False, "", 0, 0.0):
        return fallback
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def money(value) -> float:
    """Mirror JS `Math.round((Number(n)||0)*100)/100`."""
    return round(js_number_or(value, 0.0) * 100) / 100


def random_id(prefix: str) -> str:
    """Mirror `lib/auth.ts`'s `randomId(prefix)`: prefix + 6 random bytes
    rendered as uppercase hex."""
    return prefix + secrets.token_hex(6).upper()


def calculate_sales_tax(
    *, subtotal, core_charge, shipping, state, zip_code, city=None, address1=None
) -> dict:
    """Near-verbatim port of `lib/tax.ts`'s `calculateSalesTax`: TaxJar REST
    call when configured and a destination zip is present, else the static
    fallback table; TaxJar failures fall back silently, matching the
    original's `catch` swallowing errors and falling through."""
    subtotal = money(subtotal)
    core_charge = money(core_charge)
    shipping = money(shipping)
    taxable_amount = money(subtotal + core_charge)
    state = str(state or "").strip().upper()
    zip_code = str(zip_code or "").strip()

    api_key = settings.TAXJAR_API_KEY
    if api_key and zip_code:
        try:
            response = requests.post(
                "https://api.taxjar.com/v2/taxes",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from_country": "US",
                    "from_zip": settings.SHIP_FROM_ZIP or "34241",
                    "to_country": "US",
                    "to_state": state,
                    "to_zip": zip_code,
                    "to_city": city,
                    "to_street": address1,
                    "amount": taxable_amount,
                    "shipping": shipping,
                },
                timeout=10,
            )
            payload = response.json()
            if response.ok:
                tax_block = payload.get("tax") or {}
                return {
                    "tax": money(tax_block.get("amount_to_collect")),
                    "rate": float(tax_block.get("rate") or 0),
                    "source": "TaxJar destination tax",
                    "provider": "taxjar",
                    "estimated": False,
                }
        except (requests.RequestException, ValueError):
            pass

    rate = FALLBACK_TAX_RATES.get(state, 0)
    return {
        "tax": money((taxable_amount + shipping) * rate),
        "rate": rate,
        "source": "Estimated state tax - TaxJar unavailable",
        "provider": "fallback",
        "estimated": True,
    }


def resolve_or_create_customer(customer: dict) -> str | None:
    """Mirror the checkout route's inline "resolve or create customer by
    email" block: merge submitted fields into an existing row (new keys
    win) or create a fresh one with a `random_id("C")`."""
    email = customer.get("email")
    if not email:
        return None

    # Solo perfiles invitados: un email tipeado en el checkout no prueba nada,
    # así que nunca debe mezclarse con el perfil de una cuenta registrada.
    existing = Customer.objects.filter(email__iexact=email, user__isnull=True).first()
    if existing:
        existing.data = {**(existing.data or {}), **customer}
        existing.updated_at = timezone.now()
        existing.save(update_fields=["data", "updated_at"])
        return existing.pk

    customer_id = random_id("C")
    now = timezone.now()
    Customer.objects.create(
        id=customer_id,
        email=email,
        data={**customer, "id": customer_id},
        created_at=now,
        updated_at=now,
    )
    return customer_id


def next_order_number() -> str:
    """Mirror the checkout route's order-number allocation query."""
    with connection.cursor() as cursor:
        cursor.execute(
            "select coalesce(max((substring(number from '[0-9]+'))::int),10000)+1"
            " as n from orders"
        )
        (n,) = cursor.fetchone()
    return f"O{n}"


def _line_item(name: str, unit_price: float, qty: int) -> dict:
    return {
        "price_data": {
            "currency": "usd",
            "product_data": {"name": name},
            "unit_amount": round(unit_price * 100),
        },
        "quantity": qty,
    }


def create_stripe_checkout_session(order: dict):
    """Mirror `lib/stripe.ts`'s `createStripeCheckout` using the official
    SDK's `stripe.checkout.Session.create` instead of a hand-rolled
    form-encoded `fetch` to `/v1/checkout/sessions`."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    items = order.get("items") or []
    totals = order.get("totals") or {}
    app_url = settings.APP_URL or "http://localhost:3000"

    line_items = []
    for item in items:
        qty = max(1, int(js_number_or(item.get("qty") or item.get("quantity"), 1)))
        price = money(item.get("price") if item.get("price") is not None else item.get("unitPrice"))
        core = money(item.get("coreCharge"))
        title = item.get("title") or item.get("partNumber") or "Diesel Part"
        line_items.append(_line_item(title, price, qty))
        if core > 0:
            line_items.append(_line_item(f"Core charge — {title}", core, qty))

    for name, value in (
        ("Shipping", money(totals.get("shipping"))),
        ("Sales Tax", money(totals.get("tax"))),
    ):
        if value > 0:
            line_items.append(_line_item(name, value, 1))

    order_id = str(order["id"])
    params = {
        "mode": "payment",
        "client_reference_id": order_id,
        "success_url": (
            f"{app_url}/checkout-success.html?session_id={{CHECKOUT_SESSION_ID}}"
            f"&order_id={quote(order_id)}"
        ),
        "cancel_url": f"{app_url}/checkout.html?canceled=1",
        "metadata": {"order_id": order_id, "order_number": order["number"]},
        "line_items": line_items,
    }
    customer_email = (order.get("customer") or {}).get("email")
    if customer_email:
        params["customer_email"] = customer_email

    return stripe.checkout.Session.create(**params)


def get_stripe_payment_method(payment_intent_id):
    """Mirror `lib/stripe.ts`'s `getStripePaymentMethod` using the official
    SDK's `stripe.PaymentIntent.retrieve(expand=['payment_method'])`
    instead of a hand-rolled `fetch`."""
    if not settings.STRIPE_SECRET_KEY or not payment_intent_id:
        return None
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id, expand=["payment_method"])
    except stripe.error.StripeError:
        return None

    payment_method = intent.get("payment_method")
    if payment_method and hasattr(payment_method, "get"):
        card = payment_method.get("card") or {}
        return {
            "paymentIntent": intent.get("id"),
            "paymentMethodId": payment_method.get("id"),
            "brand": card.get("brand"),
            "last4": card.get("last4"),
            "funding": card.get("funding"),
        }
    return {
        "paymentIntent": intent.get("id"),
        "paymentMethodId": payment_method if isinstance(payment_method, str) else None,
    }
