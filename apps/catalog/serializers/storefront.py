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
        # El slug sale de la columna: un `slug` dentro de `data` nunca lo pisa.
        data["slug"] = instance.slug
        # `applicationIds` sale de `ProductFitment`, nunca de `data`: sin filas
        # la clave no va y el SPA cae al texto, igual que el checkout. La view
        # hace `prefetch_related("applications")`.
        data.pop("applicationIds", None)
        codes = sorted(application.code for application in instance.applications.all())
        if codes:
            data["applicationIds"] = codes
        return data


class ApplicationPublicSerializer(serializers.Serializer):

    def to_representation(self, instance):
        # El id público es `code`, el mismo que lista `applicationIds`.
        return {**instance.data, "id": instance.code}
