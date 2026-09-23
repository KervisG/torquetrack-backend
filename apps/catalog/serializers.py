"""Serializers públicos (tienda) del catálogo.

Filtrado por resta: se quitan solo los campos internos y de proveedor
conocidos y el resto del jsonb `data` se devuelve tal cual. Cualquier campo
interno NUEVO que se agregue a `data` debe sumarse explícitamente a
`RESTRICTED_PRODUCT_FIELDS` para no quedar expuesto.
"""
from rest_framework import serializers

RESTRICTED_PRODUCT_FIELDS = (
    "purchaseCost",
    "supplierCost",
    "internalNotes",
    "supplierSku",
    "supplierEmail",
    "supplierPhone",
)


class ProductPublicSerializer(serializers.Serializer):
    """Returns `instance.data` (the product jsonb) minus internal fields.

    Devuelve el objeto plano, sin envoltorio ni `id`/`active` alrededor.
    """

    def to_representation(self, instance):
        data = dict(instance.data)
        for field in RESTRICTED_PRODUCT_FIELDS:
            data.pop(field, None)
        return data


class ApplicationPublicSerializer(serializers.Serializer):
    """Returns `instance.data` (the application jsonb) unfiltered.

    No se quita ningún campo.
    """

    def to_representation(self, instance):
        return dict(instance.data)
