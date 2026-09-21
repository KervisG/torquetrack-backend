"""`POST shipping/rates` business rules (task 7.5), near-verbatim port of
`app/api/shipping/rates/route.ts`.

Reuses `apps.checkout.services.js_number_or` instead of duplicating the same
"mirror JS `Number(raw || fallback)`" helper a third time (same precedent as
`apps.quotes.admin_services` reusing `apps.checkout.services.next_order_number`).
"""
from __future__ import annotations

import base64

import requests
from django.conf import settings

from apps.catalog.models import Product
from apps.checkout.services import js_number_or


def _norm_rate(rate: dict | None) -> dict | None:
    if not rate:
        return None
    return {
        "id": rate.get("id"),
        "carrier": rate.get("carrier"),
        "service": rate.get("service"),
        "rate": float(rate.get("rate") or 0),
        "deliveryDays": rate.get("delivery_days"),
        "guaranteed": bool(rate.get("delivery_date_guaranteed")),
    }


def get_shipping_rates(payload: dict) -> tuple[dict, int]:
    api_key = settings.EASYPOST_API_KEY
    if not api_key:
        return (
            {
                "configured": False,
                "message": "EasyPost is not configured. Add EASYPOST_API_KEY to .env.local.",
            },
            200,
        )

    parcel = payload.get("parcel")
    if not parcel and payload.get("productId"):
        product = Product.objects.filter(pk=payload["productId"]).first()
        data = (product.data if product is not None else None) or {}
        parcel = {
            "weight": max(1, js_number_or(data.get("shippingWeight"), 1) * 16),
            "length": js_number_or(data.get("packageLength") or data.get("lengthIn"), 12),
            "width": js_number_or(data.get("packageWidth") or data.get("widthIn"), 10),
            "height": js_number_or(data.get("packageHeight") or data.get("heightIn"), 6),
        }

    if not parcel:
        return {"error": "Parcel information required"}, 400

    # Verbatim legacy behavior (route.ts): a weight under 50 is assumed to be
    # pounds and is converted to ounces. This applies even to a
    # product-derived parcel already expressed in ounces above — not fixed
    # here, since Phase 7 preserves existing request/response contracts
    # rather than correcting a pre-existing legacy quirk.
    if js_number_or(parcel.get("weight")) < 50:
        parcel = {**parcel, "weight": js_number_or(parcel.get("weight")) * 16}

    ship_from_zip = settings.SHIP_FROM_ZIP or "34241"
    request_payload = {
        "shipment": {
            "to_address": payload.get("to"),
            "from_address": {"zip": ship_from_zip, "country": "US"},
            "parcel": parcel,
        }
    }

    auth = base64.b64encode(f"{api_key}:".encode()).decode()
    response = requests.post(
        "https://api.easypost.com/v2/shipments",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        json=request_payload,
        timeout=15,
    )
    body = response.json()
    if not response.ok:
        message = ((body or {}).get("error") or {}).get("message") or "EasyPost rate request failed"
        return {"error": message}, 502

    rates = sorted(body.get("rates") or [], key=lambda rate: float(rate.get("rate") or 0))

    def pick(test):
        return _norm_rate(
            next((rate for rate in rates if test(str(rate.get("service") or "").lower())), None)
        )

    return (
        {
            "configured": True,
            "shipmentId": body.get("id"),
            "ground": pick(lambda service: "ground" in service),
            "secondDay": pick(
                lambda service: "2day" in service or "2nd" in service or "second" in service
            ),
            "overnight": pick(
                lambda service: "next" in service
                or "overnight" in service
                or "priority" in service
            ),
        },
        200,
    )
