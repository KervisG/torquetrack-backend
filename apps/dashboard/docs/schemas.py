"""Serializers que solo describen `GET /api/admin/dashboard/`."""
from rest_framework import serializers


class DashboardCountsSerializer(serializers.Serializer):
    orders = serializers.IntegerField()
    activeQuotes = serializers.IntegerField()
    buildingQuotes = serializers.IntegerField()
    activeCarts = serializers.IntegerField()
    abandonedCarts = serializers.IntegerField()
    salesToday = serializers.FloatField(help_text="Net sales for the current UTC day, without tax.")


class DashboardSerializer(serializers.Serializer):
    counts = DashboardCountsSerializer()
