"""Serializers que solo describen `POST /api/tax/estimate/`."""
from rest_framework import serializers


class TaxEstimateRequestSerializer(serializers.Serializer):
    state = serializers.CharField(help_text="Two-letter state. Used with the ZIP.")
    zip = serializers.CharField()
    subtotal = serializers.FloatField(required=False)
    shipping = serializers.FloatField(required=False)


class TaxEstimateSerializer(serializers.Serializer):
    tax = serializers.FloatField()
    rate = serializers.FloatField()
    source = serializers.CharField()
    provider = serializers.CharField()
    estimated = serializers.BooleanField()
