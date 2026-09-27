"""Los estados del dominio son `TextChoices` en el módulo del modelo dueño.

Sin endpoints ni proveedores que mockear: se leen los `choices` de cada campo y
los miembros de cada enum. Los valores esperados son el contrato del JSON y
coinciden con los que usa el frontend (`features/admin/orders/types.ts`,
`features/admin/quotes/types.ts`, `features/admin/customers/types.ts`,
`features/admin/carts/pages/carts-page.tsx`). Cambiar un valor aquí rompe al
SPA, así que el test fija los strings literales a propósito.
"""
import pytest

from apps.cart.models import Cart, CartStage, CartStatus
from apps.checkout.models import (
    Carrier,
    CoreStatus,
    FulfillmentStatus,
    Order,
    OrderPaymentStatus,
    OrderStatus,
    Payment,
    PaymentStatus,
    Refund,
    RefundStatus,
    ReturnStatus,
)
from apps.checkout.services import (
    CHARGED_PAYMENT_STATUSES,
    CLOSED_ORDER_STATUSES,
    ORDER_STATUS_TRANSITIONS,
)
from apps.checkout.services.fulfillment import FULFILLMENT_TRANSITIONS
from apps.checkout.services.refunds import (
    FINAL_REFUND_STATUSES,
    HELD_REFUND_STATUSES,
    REFUNDABLE_ORDER_STATUSES,
    STRIPE_REFUND_STATUSES,
)
from apps.customers.models import Customer, PortalStatus, TaxStatus
from apps.quotes.models import Quote, QuoteStatus
from apps.quotes.services import EXPIRABLE_QUOTE_STATUSES, PAYABLE_QUOTE_STATUSES
from apps.quotes.services.admin import CONVERTIBLE_QUOTE_STATUSES


def _choice_values(model, field_name):
    return {value for value, _label in model._meta.get_field(field_name).choices}


@pytest.mark.parametrize(
    ("model", "field_name", "enum", "expected"),
    [
        (
            Order,
            "status",
            OrderStatus,
            {"OPEN", "PENDING_PAYMENT", "PROCESSING", "COMPLETED", "CANCELLED", "REJECTED"},
        ),
        (
            Order,
            "payment_status",
            OrderPaymentStatus,
            {"UNPAID", "PAID", "FAILED", "PARTIALLY_REFUNDED", "REFUNDED"},
        ),
        (
            Payment,
            "status",
            PaymentStatus,
            {"PENDING", "PAID", "FAILED", "CANCELLED", "PARTIALLY_REFUNDED", "REFUNDED"},
        ),
        (Refund, "status", RefundStatus, {"PENDING", "SUCCEEDED", "FAILED", "CANCELED"}),
        (
            Order,
            "fulfillment_status",
            FulfillmentStatus,
            {"UNFULFILLED", "PREPARING", "SHIPPED", "DELIVERED"},
        ),
        (Order, "carrier", Carrier, {"UPS", "FEDEX", "USPS", "OTHER"}),
        (
            Quote,
            "status",
            QuoteStatus,
            {"BUILDING", "ACTIVE", "CONTACTED", "EXPIRED", "CONVERTED", "LOST"},
        ),
        (
            Customer,
            "tax_status",
            TaxStatus,
            {"VERIFIED", "REJECTED", "EXPIRED", "PENDING VERIFICATION", "NOT SUBMITTED"},
        ),
    ],
)
def test_status_fields_declare_exactly_the_contract_values(model, field_name, enum, expected):
    assert set(enum.values) == expected
    assert _choice_values(model, field_name) == expected


@pytest.mark.parametrize(
    ("model", "field_name", "default"),
    [
        (Order, "status", "OPEN"),
        (Order, "payment_status", "UNPAID"),
        (Order, "fulfillment_status", "UNFULFILLED"),
        (Refund, "status", "PENDING"),
        (Quote, "status", "BUILDING"),
        (Customer, "tax_status", "NOT SUBMITTED"),
    ],
)
def test_status_defaults_keep_their_values(model, field_name, default):
    field = model._meta.get_field(field_name)

    assert field.default == default
    assert field.db_default.value == default


# Estados que viven dentro de un JSONField (`Order.data`, `Cart.data`) o que
# se derivan al serializar: no tienen columna ni migración.
@pytest.mark.parametrize(
    ("enum", "expected"),
    [
        (
            CoreStatus,
            {
                "AWAITING CORE",
                "IN TRANSIT",
                "RECEIVED",
                "INSPECTING",
                "ACCEPTED",
                "REJECTED",
                "REFUNDED",
            },
        ),
        (
            ReturnStatus,
            {
                "REQUESTED",
                "APPROVED",
                "IN TRANSIT",
                "RECEIVED",
                "INSPECTING",
                "REFUNDED",
                "REJECTED",
            },
        ),
        (CartStage, {"CART", "CHECKOUT", "BUILDING_QUOTE"}),
        (CartStatus, {"ACTIVE", "ABANDONED", "CHECKOUT", "BUILDING_QUOTE", "EMPTY"}),
        (PortalStatus, {"ACTIVE", "INVITED", "NOT ACTIVATED"}),
    ],
)
def test_json_status_enums_declare_exactly_the_contract_values(enum, expected):
    assert set(enum.values) == expected


def test_cart_has_no_status_column():
    # `user` liga el carrito a la cuenta; la etapa y el estado siguen en `data`.
    assert {field.name for field in Cart._meta.get_fields()} == {
        "id",
        "user",
        "data",
        "updated_at",
    }


def test_status_sets_are_built_from_the_enum_members():
    assert set(CHARGED_PAYMENT_STATUSES) == {"PAID", "PARTIALLY_REFUNDED", "REFUNDED"}
    # Los mismos valores valen para `Payment.status` y `Order.payment_status`.
    assert set(CHARGED_PAYMENT_STATUSES) <= set(PaymentStatus.values)
    assert set(CHARGED_PAYMENT_STATUSES) <= set(OrderPaymentStatus.values)
    assert set(CLOSED_ORDER_STATUSES) == {"CANCELLED", "REJECTED"}
    assert set(REFUNDABLE_ORDER_STATUSES) == {"PAID", "PARTIALLY_REFUNDED"}
    assert set(HELD_REFUND_STATUSES) == {"PENDING", "SUCCEEDED"}
    assert set(FINAL_REFUND_STATUSES) == {"SUCCEEDED", "FAILED", "CANCELED"}
    assert set(STRIPE_REFUND_STATUSES.values()) <= set(RefundStatus.values)
    assert set(EXPIRABLE_QUOTE_STATUSES) == {"BUILDING", "ACTIVE", "CONTACTED"}
    assert set(PAYABLE_QUOTE_STATUSES) == {"ACTIVE", "CONTACTED", "CONVERTED"}
    assert set(CONVERTIBLE_QUOTE_STATUSES) == {"ACTIVE", "CONTACTED"}
    assert FULFILLMENT_TRANSITIONS == {
        "UNFULFILLED": {"PREPARING", "SHIPPED"},
        "PREPARING": {"SHIPPED"},
        "SHIPPED": {"DELIVERED"},
        "DELIVERED": set(),
    }
    assert ORDER_STATUS_TRANSITIONS == {
        "PENDING_PAYMENT": {"CANCELLED", "REJECTED"},
        "OPEN": {"PROCESSING", "CANCELLED", "REJECTED"},
        "PROCESSING": {"COMPLETED", "CANCELLED", "REJECTED"},
        "COMPLETED": set(),
        "CANCELLED": set(),
        "REJECTED": set(),
    }

    members = [
        *CHARGED_PAYMENT_STATUSES,
        *CLOSED_ORDER_STATUSES,
        *REFUNDABLE_ORDER_STATUSES,
        *HELD_REFUND_STATUSES,
        *FINAL_REFUND_STATUSES,
        *STRIPE_REFUND_STATUSES.values(),
        *EXPIRABLE_QUOTE_STATUSES,
        *PAYABLE_QUOTE_STATUSES,
        *CONVERTIBLE_QUOTE_STATUSES,
        *FULFILLMENT_TRANSITIONS,
        *(value for targets in FULFILLMENT_TRANSITIONS.values() for value in targets),
        *ORDER_STATUS_TRANSITIONS,
        *(value for targets in ORDER_STATUS_TRANSITIONS.values() for value in targets),
    ]
    assert all(type(value) is not str for value in members)
