"""Serializers que solo describen `GET /api/vin/`."""
from rest_framework import serializers


class VehicleSerializer(serializers.Serializer):
    vin = serializers.CharField()
    year = serializers.CharField(allow_blank=True)
    make = serializers.CharField(allow_blank=True)
    model = serializers.CharField(allow_blank=True)
    engine = serializers.CharField(allow_blank=True)
    engineModel = serializers.CharField(allow_blank=True)
    fuelType = serializers.CharField(allow_blank=True)


class VinDecodeSerializer(serializers.Serializer):
    vehicle = VehicleSerializer()
