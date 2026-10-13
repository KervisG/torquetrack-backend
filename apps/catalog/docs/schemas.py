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


class ProductFacetsSerializer(serializers.Serializer):
    brands = serializers.ListField(child=serializers.CharField())
    categories = serializers.ListField(child=serializers.CharField())
    conditions = serializers.ListField(child=serializers.CharField())
    priceCeiling = serializers.IntegerField()


class ProductPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    pageSize = serializers.IntegerField()
    pageCount = serializers.IntegerField()
    results = CatalogRecordSerializer(many=True)
    facets = ProductFacetsSerializer(
        required=False, help_text="Filter options from the whole catalog. Omitted with `ids`."
    )
    overview = serializers.DictField(
        required=False,
        help_text=(
            "Only with `overview`: `productCount`, `categories` (value, label, count, brands) "
            "and `makes` (name, count), for the storefront home page."
        ),
    )


class ProductImageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    url = serializers.URLField()
    alt = serializers.CharField(allow_blank=True)
    position = serializers.IntegerField(help_text="0 is the cover.")
    width = serializers.IntegerField(allow_null=True)
    height = serializers.IntegerField(allow_null=True)


class ProductGallerySerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    images = ProductImageSerializer(many=True)


class ProductImageUploadSerializer(serializers.Serializer):
    file = serializers.ImageField(help_text="JPG, PNG or WebP, up to 4 MB.")
    alt = serializers.CharField(required=False, allow_blank=True)


class AdminBrandSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    logo = serializers.CharField(allow_null=True, help_text="Public URL of the logo, if any.")
    active = serializers.BooleanField()
    productCount = serializers.IntegerField(
        help_text="Products that carry the brand in `manufacturer`, active or not."
    )


class AdminBrandResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    brand = AdminBrandSerializer()


class AdminBrandCreateSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Unique, case-insensitive. Cannot contain `/`.")


class AdminBrandActiveSerializer(serializers.Serializer):
    active = serializers.BooleanField()


class AdminBrandLogoUploadSerializer(serializers.Serializer):
    file = serializers.ImageField(help_text="JPG, PNG or WebP, up to 4 MB.")


class ProductImageOrderSerializer(serializers.Serializer):
    order = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="Every image id of the product, in the new order. The first is the cover.",
    )
