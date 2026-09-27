"""Serializers que solo describen las rutas de cotizaciones."""
from rest_framework import serializers

from apps.quotes.models import QuoteStatus


class QuoteSerializer(serializers.Serializer):
    id = serializers.CharField()
    number = serializers.CharField(required=False)
    status = serializers.ChoiceField(choices=QuoteStatus.choices, required=False)


class QuoteWriteSerializer(serializers.Serializer):
    customerName = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)


class QuoteRequestSerializer(serializers.Serializer):
    name = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class VinRequestSerializer(serializers.Serializer):
    vin = serializers.CharField()


class QuoteTaxRequestSerializer(serializers.Serializer):
    state = serializers.CharField(required=False)
    zip = serializers.CharField(required=False)
    customerId = serializers.CharField(required=False)


class CheckoutLinkSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    url = serializers.URLField(required=False, allow_null=True)
