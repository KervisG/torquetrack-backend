"""Public (storefront) serializers for the catalog app.

Whitelist-by-subtraction, matching `app/api/products/route.ts`'s `clean()`:
strip only the known internal/supplier fields, keep everything else in the
`data` jsonb blob as-is. Design decision (DRF Conventions) requires
whitelisting, not `exclude`, so any NEW internal field added to `data` in
the future is NOT silently exposed here without an explicit change to this
list.
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

    Mirrors `app/api/products/route.ts`'s bare-object shape exactly — no
    envelope, no wrapping of `id`/`active` around it.
    """

    def to_representation(self, instance):
        data = dict(instance.data)
        for field in RESTRICTED_PRODUCT_FIELDS:
            data.pop(field, None)
        return data


class ApplicationPublicSerializer(serializers.Serializer):
    """Returns `instance.data` (the application jsonb) unfiltered.

    Mirrors `app/api/applications/route.ts`, which never strips any field.
    """

    def to_representation(self, instance):
        return dict(instance.data)
