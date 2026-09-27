"""Filtrado por resta: todo campo interno nuevo de `data` debe sumarse a
`RESTRICTED_PRODUCT_FIELDS` para no quedar expuesto en la tienda."""
from rest_framework import serializers

RESTRICTED_PRODUCT_FIELDS = (
    "purchaseCost",
    "supplierCost",
    "internalNotes",
    "supplierSku",
    "supplierEmail",
    "supplierPhone",
    # Proveedor y costo los carga el panel de productos; la tienda no los
    # muestra y revelarlos expone márgenes y a quién se le compra.
    "supplier",
    "supplierPartNumber",
    "supplierUrl",
    "cost",
)


class ProductPublicSerializer(serializers.Serializer):

    def to_representation(self, instance):
        data = dict(instance.data)
        for field in RESTRICTED_PRODUCT_FIELDS:
            data.pop(field, None)
        return data


class ApplicationPublicSerializer(serializers.Serializer):

    def to_representation(self, instance):
        return dict(instance.data)
