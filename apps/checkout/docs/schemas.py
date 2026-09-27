"""Serializers que solo describen bodies del esquema OpenAPI de
`apps.checkout`; ninguna view los usa en runtime."""
from rest_framework import serializers


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
    status = serializers.ChoiceField(choices=["PENDING", "SUCCEEDED", "FAILED", "CANCELED"])
    reason = serializers.CharField(allow_blank=True)
    createdBy = serializers.CharField(help_text="Staff email, or `stripe` for dashboard refunds.")
    createdAt = serializers.DateTimeField()
    stripeRefundId = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Only with the `payments.transaction_id` permission.",
    )
