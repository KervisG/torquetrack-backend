"""Serializers que solo describen los bodies de `/api/cart/` y
`/api/admin/carts/` en el esquema.

Sin docstrings en las clases: drf-spectacular los publica como descripción.
"""
from rest_framework import serializers


class CartItemInputSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Active catalog product id.")
    qty = serializers.IntegerField(min_value=1, max_value=99)


class CartRequestSerializer(serializers.Serializer):
    items = CartItemInputSerializer(
        many=True, help_text="Replaces every line. An empty list deletes the cart."
    )
    acknowledgePrices = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Only the boolean `true` accepts the price notices: every saved line takes the "
            "current catalog price as its new reference. Without it, lines already in the cart "
            "keep their reference and the notice stays."
        ),
    )


class CartLineSerializer(serializers.Serializer):
    id = serializers.CharField()
    qty = serializers.IntegerField()
    title = serializers.CharField()
    partNumber = serializers.CharField(allow_blank=True)
    price = serializers.FloatField(
        allow_null=True, help_text="Current catalog price; `null` when it has no valid price."
    )
    coreCharge = serializers.FloatField(allow_null=True)
    lineTotal = serializers.FloatField(allow_null=True)
    priceChanged = serializers.BooleanField(
        help_text=(
            "The current price differs from the catalog price when the product was added "
            "(or when the last notice was acknowledged)."
        )
    )
    previousPrice = serializers.FloatField(
        required=False, help_text="Reference price; only present when `priceChanged` is true."
    )


class CartSerializer(serializers.Serializer):
    items = CartLineSerializer(many=True)
    subtotal = serializers.FloatField(help_text="Sum of the priced lines, before core.")
    core = serializers.FloatField()
    notices = serializers.ListField(
        child=serializers.CharField(),
        help_text="One `The price of <title> has changed from $A to $B.` per changed line.",
    )


class AdminCartItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    qty = serializers.IntegerField()
    title = serializers.CharField()
    partNumber = serializers.CharField(allow_blank=True)
    priceAtAdd = serializers.FloatField(
        required=False,
        help_text="Catalog price when the product was added; only for the price notice.",
    )


class AdminCartSerializer(serializers.Serializer):
    id = serializers.CharField()
    status = serializers.ChoiceField(choices=["ACTIVE", "ABANDONED", "CHECKOUT", "BUILDING_QUOTE"])
    stage = serializers.ChoiceField(choices=["CART", "CHECKOUT", "BUILDING_QUOTE"])
    updatedAt = serializers.DateTimeField()
    email = serializers.EmailField(required=False, help_text="Account email of a signed-in cart.")
    items = AdminCartItemSerializer(many=True)
