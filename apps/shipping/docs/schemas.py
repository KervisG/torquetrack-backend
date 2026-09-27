"""Serializers que solo describen `POST /api/shipping/rates/`."""
from rest_framework import serializers


class ShippingAddressSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    street1 = serializers.CharField()
    street2 = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField()
    state = serializers.CharField()
    zip = serializers.CharField()
    country = serializers.CharField(required=False)


class ShippingItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    qty = serializers.IntegerField()


class ShippingRateSerializer(serializers.Serializer):
    id = serializers.CharField()
    shipmentId = serializers.CharField()
    carrier = serializers.CharField()
    service = serializers.CharField()
    rate = serializers.FloatField()


class ShippingRatesRequestSerializer(serializers.Serializer):
    to = ShippingAddressSerializer()
    items = ShippingItemSerializer(many=True)


class ShippingRatesSerializer(serializers.Serializer):
    configured = serializers.BooleanField()
    shipmentId = serializers.CharField(required=False, allow_null=True)
    ground = ShippingRateSerializer(allow_null=True)
    secondDay = ShippingRateSerializer(allow_null=True)
    overnight = ShippingRateSerializer(allow_null=True)
