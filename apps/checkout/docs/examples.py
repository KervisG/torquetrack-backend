"""Ejemplos del esquema OpenAPI de `apps.checkout`. Los mensajes son los
literales de `services/refunds.py` y `services/fulfillment.py`; si uno cambia
en el código, hay que cambiarlo aquí."""
from drf_spectacular.utils import OpenApiExample

from apps.authorization.docs.examples import error_example
from apps.checkout.models import Carrier, FulfillmentStatus, RefundStatus
from apps.common.us_addresses import (
    INVALID_SHIPPING_STATE,
    INVALID_SHIPPING_ZIP,
    SHIPPING_STATE_REQUIRED,
    UNKNOWN_SHIPPING_ZIP,
    ZIP_STATE_MISMATCH,
)

REFUND_REQUEST = OpenApiExample(
    "Partial refund",
    value={"amount": 25.5, "reason": "Damaged on arrival"},
    request_only=True,
)
REFUND_CREATED = OpenApiExample(
    "Refund succeeded",
    value={
        "id": "RFD0A1B2C3D4E5F",
        "paymentId": "PAY0A1B2C3D4E5F",
        "amount": 25.5,
        "status": RefundStatus.SUCCEEDED.value,
        "reason": "Damaged on arrival",
        "createdBy": "staff@example.com",
        "createdAt": "2026-09-27T12:00:00Z",
    },
    response_only=True,
)

INVALID_AMOUNT = error_example(
    "Invalid amount", "Refund amount must be a positive number with at most two decimals"
)
AMOUNT_OVER_BALANCE = error_example(
    "Amount over balance", "Refund amount exceeds the refundable balance of $70.00"
)
REASON_NOT_TEXT = error_example("Reason is not text", "Refund reason must be text")
REASON_TOO_LONG = error_example(
    "Reason too long", "Refund reason must be 500 characters or fewer"
)
ORDER_NOT_FOUND = error_example("Order not found", "Order not found")
NOT_PAID = error_example("Order not paid", "Only paid orders can be refunded")
NO_STRIPE_CHARGE = error_example("No Stripe charge", "Order has no Stripe charge to refund")
NO_BALANCE = error_example("No balance left", "Order has no refundable balance")
STRIPE_FAILED = error_example("Stripe failed", "Stripe request failed; see server logs.")

FULFILLMENT_SHIP_REQUEST = OpenApiExample(
    "Mark shipped",
    value={
        "status": FulfillmentStatus.SHIPPED.value,
        "carrier": Carrier.UPS.value,
        "trackingNumber": "1Z999AA10123456784",
    },
    request_only=True,
)
FULFILLMENT_PREPARING_REQUEST = OpenApiExample(
    "Mark preparing", value={"status": FulfillmentStatus.PREPARING.value}, request_only=True
)
FULFILLMENT_SHIPPED = OpenApiExample(
    "Shipped",
    value={
        "id": "OID0A1B2C3D4E5F",
        "number": "O10042",
        "fulfillmentStatus": FulfillmentStatus.SHIPPED.value,
        "carrier": Carrier.UPS.value,
        "trackingNumber": "1Z999AA10123456784",
        "trackingUrl": "https://www.ups.com/track?tracknum=1Z999AA10123456784",
        "shippedAt": "2026-09-27T12:00:00Z",
        "deliveredAt": None,
    },
    response_only=True,
)

INVALID_FULFILLMENT_STATUS = error_example("Invalid status", "Invalid fulfillment status")
INVALID_CARRIER = error_example("Invalid carrier", "Carrier must be one of UPS, FEDEX, USPS, OTHER")
TRACKING_REQUIRED = error_example(
    "Tracking number missing", "Tracking number is required to ship an order"
)
INVALID_TRACKING = error_example(
    "Invalid tracking number", "Tracking number must be 1 to 64 letters, digits or hyphens"
)
SHIPMENT_FIELDS_NOT_ALLOWED = error_example(
    "Shipment fields without SHIPPED",
    "Carrier and tracking number can only be set when marking an order SHIPPED",
)
FULFILLMENT_NOT_PAID = error_example("Order not paid", "Only paid orders can be fulfilled")
FULFILLMENT_CLOSED = error_example("Closed order", "Closed orders cannot be fulfilled")
FULFILLMENT_BACKWARDS = error_example(
    "Backward transition", "Cannot move fulfillment from SHIPPED to PREPARING"
)
FULFILLMENT_ALREADY = error_example("Same status", "Fulfillment is already PREPARING")
FULFILLMENT_SAME_TRACKING = error_example(
    "Same tracking number", "Order already shipped with this tracking number"
)


SHIPPING_STATE_MISSING = error_example(
    "Shipping state missing", SHIPPING_STATE_REQUIRED, "state"
)
SHIPPING_STATE_INVALID = error_example("Shipping state invalid", INVALID_SHIPPING_STATE, "state")
SHIPPING_ZIP_INVALID = error_example("Shipping ZIP invalid", INVALID_SHIPPING_ZIP, "zip")
SHIPPING_ZIP_UNKNOWN = error_example("Shipping ZIP unassigned", UNKNOWN_SHIPPING_ZIP, "zip")
SHIPPING_ZIP_MISMATCH = error_example("ZIP from another state", ZIP_STATE_MISMATCH, "zip")
