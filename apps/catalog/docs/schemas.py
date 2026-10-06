"""Serializers que solo describen el catálogo público y el del panel."""
from rest_framework import serializers


class CatalogRecordSerializer(serializers.Serializer):
    id = serializers.CharField()
    slug = serializers.SlugField(
        help_text="Stable SEO slug, generated on create; the storefront URL is /product/<slug>."
    )
    title = serializers.CharField(required=False)
    partNumber = serializers.CharField(required=False, allow_blank=True)
    price = serializers.FloatField(required=False)


class AdminProductWriteSerializer(serializers.Serializer):
    title = serializers.CharField()
    price = serializers.FloatField(required=False, help_text="Requires `pricing.edit` to change.")
    applicationIds = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text=(
            "Compatible application codes (`GET /api/admin/applications/`). Omit to keep "
            "the current list; `[]` clears it. Unknown codes are rejected with 400."
        ),
    )
