"""Serializers que solo describen `GET /api/vin/`."""
from rest_framework import serializers


class VehicleDetailsSerializer(serializers.Serializer):
    engine = serializers.CharField(allow_blank=True)
    drivetrain = serializers.CharField(allow_blank=True)
    transmission = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True)
    trim = serializers.CharField(allow_blank=True)
    gvwr = serializers.CharField(allow_blank=True)
    fuel = serializers.CharField(allow_blank=True)
    horsepower = serializers.CharField(allow_blank=True)
    vehicleType = serializers.CharField(allow_blank=True)
    series = serializers.CharField(allow_blank=True)
    cab = serializers.CharField(allow_blank=True)
    brakes = serializers.CharField(allow_blank=True)
    manufacturer = serializers.CharField(allow_blank=True)
    plant = serializers.CharField(allow_blank=True)


class VehicleSpecSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = serializers.CharField()


class VehicleSerializer(serializers.Serializer):
    vin = serializers.CharField()
    year = serializers.CharField(allow_blank=True)
    make = serializers.CharField(allow_blank=True)
    model = serializers.CharField(allow_blank=True)
    engine = serializers.CharField(allow_blank=True)
    engineModel = serializers.CharField(allow_blank=True)
    fuelType = serializers.CharField(allow_blank=True)
    details = VehicleDetailsSerializer()
    specs = VehicleSpecSerializer(many=True)


class VinDecodeSerializer(serializers.Serializer):
    vehicle = VehicleSerializer()
    # Campos de `vehicle` que el VIN no trajo: year, make, model o engine.
    missingFields = serializers.ListField(child=serializers.CharField())
    # Códigos de aviso; `check_digit` = el VIN probablemente está mal tipeado.
    warnings = serializers.ListField(child=serializers.CharField())
