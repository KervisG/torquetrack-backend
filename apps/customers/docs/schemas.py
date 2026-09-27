"""Serializers que solo describen las rutas de cuentas y clientes."""
from rest_framework import serializers


class MessageSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField(required=False)


class RegisterRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()
    firstName = serializers.CharField(required=False, allow_blank=True)
    lastName = serializers.CharField(required=False, allow_blank=True)


class TokenRequestSerializer(serializers.Serializer):
    token = serializers.CharField()


class CustomerSerializer(serializers.Serializer):
    id = serializers.CharField()
    email = serializers.EmailField(allow_null=True)
    name = serializers.CharField(allow_blank=True)
    company = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    taxStatus = serializers.CharField()
    portalStatus = serializers.CharField(required=False)


class TaxStatusRequestSerializer(serializers.Serializer):
    status = serializers.CharField()


class PortalInviteRequestSerializer(serializers.Serializer):
    customerId = serializers.CharField()
