"""Serializers que solo describen `POST /api/tax/estimate/`."""
from rest_framework import serializers

from apps.common.us_addresses import US_STATE_CODES


class TaxEstimateRequestSerializer(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=sorted(US_STATE_CODES),
        required=False,
        help_text=(
            "Two-letter code of a US state, DC or inhabited territory (or `address.state`). "
            "Required unless the signed-in customer is tax exempt."
        ),
    )
    zip = serializers.CharField()
    subtotal = serializers.FloatField(required=False)
    shipping = serializers.FloatField(required=False)


class TaxEstimateSerializer(serializers.Serializer):
    tax = serializers.FloatField()
    rate = serializers.FloatField()
    source = serializers.CharField()
    provider = serializers.CharField()
    estimated = serializers.BooleanField()
