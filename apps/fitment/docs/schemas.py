"""Serializers que solo describen `POST /api/fitment/check/`."""
from rest_framework import serializers


class FitmentVehicleSerializer(serializers.Serializer):
    year = serializers.CharField(required=False, allow_blank=True)
    make = serializers.CharField(required=False, allow_blank=True)
    model = serializers.CharField(required=False, allow_blank=True)
    engine = serializers.CharField(required=False, allow_blank=True)
    vin = serializers.CharField(required=False, allow_blank=True)


class FitmentItemSerializer(serializers.Serializer):
    id = serializers.CharField()


class FitmentCheckRequestSerializer(serializers.Serializer):
    vehicle = FitmentVehicleSerializer()
    items = FitmentItemSerializer(many=True)


class FitmentCheckSerializer(serializers.Serializer):
    compatible = serializers.BooleanField()
    reasons = serializers.ListField(child=serializers.CharField())
    warnings = serializers.ListField(child=serializers.CharField())
