"""Reglas de negocio de `POST shipping/rates` (tarifas de EasyPost).

La llamada HTTP vive en el adaptador `apps.integrations.shipping.easypost`.
Aquí quedan las reglas de la tienda: derivar el paquete del producto,
convertir libras a onzas, el origen del envío y elegir las tres opciones que
ve el cliente (ground, 2 días y overnight).

Reutiliza `apps.checkout.services.js_number_or` para la conversión numérica
con valor por defecto, en lugar de duplicar ese helper.
"""
from __future__ import annotations

from django.conf import settings

from apps.catalog.models import Product
from apps.checkout.services import js_number_or
from apps.integrations.exceptions import ProviderError
from apps.integrations.shipping import easypost


def _norm_rate(rate: dict | None) -> dict | None:
    if not rate:
        return None
    return {
        "id": rate["id"],
        "carrier": rate["carrier"],
        "service": rate["service"],
        "rate": rate["rate"],
        "deliveryDays": rate["delivery_days"],
        "guaranteed": rate["guaranteed"],
    }


def get_shipping_rates(payload: dict) -> tuple[dict, int]:
    if not easypost.is_configured():
        return (
            {
                "configured": False,
                "message": (
                    "EasyPost is not configured. Add EASYPOST_API_KEY to the server environment."
                ),
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

    # Comportamiento intencional del contrato: un peso menor a 50 se asume en
    # libras y se convierte a onzas. Esto aplica incluso al paquete derivado
    # del producto, que arriba ya se expresó en onzas; el contrato de
    # request/response se mantiene tal cual y los tests lo fijan.
    if js_number_or(parcel.get("weight")) < 50:
        parcel = {**parcel, "weight": js_number_or(parcel.get("weight")) * 16}

    try:
        shipment = easypost.get_rates(
            to_address=payload.get("to"),
            from_address={"zip": settings.SHIP_FROM_ZIP or "34241", "country": "US"},
            parcel=parcel,
        )
    except ProviderError as exc:
        return {"error": str(exc)}, 502

    rates = sorted(shipment["rates"], key=lambda rate: rate["rate"])

    def pick(test):
        return _norm_rate(
            next((rate for rate in rates if test(str(rate.get("service") or "").lower())), None)
        )

    return (
        {
            "configured": True,
            "shipmentId": shipment["shipment_id"],
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
