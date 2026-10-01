"""Serializers que solo describen bodies del esquema OpenAPI de
`apps.checkout`; ninguna view los usa en runtime."""
from rest_framework import serializers

from apps.checkout.models import Carrier, FulfillmentStatus, RefundStatus
from apps.common.us_addresses import US_STATE_CODES


class RefundRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        coerce_to_string=False,
        required=False,
        help_text="Dollars, up to two decimals. Omit it to refund the remaining balance.",
    )
    reason = serializers.CharField(
        required=False,
        max_length=500,
        help_text="Internal note, sent to Stripe as metadata.",
    )


class RefundSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Refund id (prefix `RFD`).")
    paymentId = serializers.CharField()
    amount = serializers.FloatField()
    status = serializers.ChoiceField(choices=RefundStatus.choices)
    reason = serializers.CharField(allow_blank=True)
    createdBy = serializers.CharField(help_text="Staff email, or `stripe` for dashboard refunds.")
    createdAt = serializers.DateTimeField()
    stripeRefundId = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Only with the `payments.transaction_id` permission.",
    )


class OrderSummarySerializer(serializers.Serializer):
    id = serializers.CharField()
    number = serializers.CharField()
    status = serializers.CharField()
    paymentStatus = serializers.CharField()
    createdAt = serializers.DateTimeField()


class OrderPatchSerializer(serializers.Serializer):
    status = serializers.CharField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class CheckoutItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    qty = serializers.IntegerField(min_value=1, max_value=99)


class CheckoutCustomerSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    company = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(
        required=False, help_text="Ignored for a signed-in customer: the account email is used."
    )
    phone = serializers.CharField(required=False, allow_blank=True)
    address1 = serializers.CharField(required=False)
    address2 = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False)
    state = serializers.ChoiceField(
        choices=sorted(US_STATE_CODES),
        help_text=(
            "Required. Two-letter code of a US state, DC or an inhabited territory; "
            "case-insensitive and stored uppercase. Full names are rejected. "
            "Sales tax is charged only for the nexus states."
        ),
    )
    zip = serializers.RegexField(
        r"^\d{5}(-\d{4})?$",
        help_text=(
            "Required. 5 digits or ZIP+4; must match the ZIP the shipping rate was quoted for."
        ),
    )
    country = serializers.CharField(required=False, help_text="Only US addresses are shipped to.")


class CheckoutShippingSelectionSerializer(serializers.Serializer):
    shipmentId = serializers.CharField()
    rateId = serializers.CharField()


class CheckoutRequestSerializer(serializers.Serializer):
    items = CheckoutItemSerializer(many=True)
    customer = CheckoutCustomerSerializer(help_text="Shipping address and contact.")
    vehicle = serializers.DictField(
        required=False, help_text="Optional. With a `vin`, the cart must pass the fitment check."
    )
    shipping = CheckoutShippingSelectionSerializer(
        help_text="A rate returned by `POST /api/shipping/rates/`."
    )


class CheckoutResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    url = serializers.URLField(required=False, allow_null=True)
    orderId = serializers.CharField(required=False)
    orderNumber = serializers.CharField(required=False)


class PaymentLinkSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    url = serializers.URLField(required=False, allow_null=True)
    emailed = serializers.BooleanField(required=False)


class WebhookAckSerializer(serializers.Serializer):
    received = serializers.BooleanField()


class FulfillmentRequestSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=FulfillmentStatus.choices)
    carrier = serializers.ChoiceField(
        choices=Carrier.values,
        required=False,
        help_text="Required with `SHIPPED`; rejected with any other status.",
    )
    trackingNumber = serializers.CharField(
        required=False,
        max_length=64,
        help_text="Required with `SHIPPED`: 1 to 64 letters, digits or hyphens.",
    )


class FulfillmentSerializer(serializers.Serializer):
    id = serializers.CharField()
    number = serializers.CharField()
    fulfillmentStatus = serializers.ChoiceField(choices=FulfillmentStatus.choices)
    carrier = serializers.CharField(
        allow_blank=True, help_text="`UPS`, `FEDEX`, `USPS`, `OTHER`, or empty before shipping."
    )
    trackingNumber = serializers.CharField(allow_blank=True)
    trackingUrl = serializers.URLField(
        allow_null=True, help_text="Public carrier tracking page; null for `OTHER`."
    )
    shippedAt = serializers.DateTimeField(allow_null=True)
    deliveredAt = serializers.DateTimeField(allow_null=True)
