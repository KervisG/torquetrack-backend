"""Serializers que solo describen el catálogo público y el del panel."""
from rest_framework import serializers


class CatalogRecordSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField(required=False)
    partNumber = serializers.CharField(required=False, allow_blank=True)
    price = serializers.FloatField(required=False)


class AdminProductWriteSerializer(serializers.Serializer):
    title = serializers.CharField()
    price = serializers.FloatField(required=False, help_text="Requires `pricing.edit` to change.")
