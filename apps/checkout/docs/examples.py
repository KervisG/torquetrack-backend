"""Ejemplos del esquema OpenAPI de `apps.checkout`. Los mensajes son los
literales de `services/refunds.py`; si uno cambia en el código, hay que
cambiarlo aquí."""
from drf_spectacular.utils import OpenApiExample

from apps.authorization.docs.examples import error_example

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
        "status": "SUCCEEDED",
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
