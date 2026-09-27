"""Serializers que solo describen el body de `GET /api/health/` en el esquema.

Sin docstrings en las clases: drf-spectacular los publica como descripción.
"""
from rest_framework import serializers


class HealthOkResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()


class HealthUnavailableResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    error = serializers.CharField()
