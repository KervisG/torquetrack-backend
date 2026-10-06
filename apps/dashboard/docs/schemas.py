"""Serializers que solo describen `GET /api/admin/dashboard/` y
`GET /api/admin/dashboard/analytics/`."""
from rest_framework import serializers


class DashboardCountsSerializer(serializers.Serializer):
    orders = serializers.IntegerField()
    activeQuotes = serializers.IntegerField()
    buildingQuotes = serializers.IntegerField()
    activeCarts = serializers.IntegerField()
    abandonedCarts = serializers.IntegerField()
    salesToday = serializers.FloatField(
        help_text="Net sales for the store's current day (STORE_TIME_ZONE), without tax."
    )


class DashboardSerializer(serializers.Serializer):
    counts = DashboardCountsSerializer()


# El dinero de la analítica sale como número redondeado a centavos (`money`),
# igual que `salesToday`.


class RevenuePointSerializer(serializers.Serializer):
    date = serializers.DateField(help_text="Day, or first day of the month with `12m`.")
    revenue = serializers.FloatField(help_text="Net sales without tax, minus refunds.")
    orders = serializers.IntegerField(help_text="Orders with a payment charged in the bucket.")


class MoneyKpiSerializer(serializers.Serializer):
    value = serializers.FloatField()
    previous = serializers.FloatField(help_text="Same metric in the previous period.")
    changePercent = serializers.FloatField(
        allow_null=True, help_text="Percent change; null when the previous value is 0."
    )


class CountKpiSerializer(serializers.Serializer):
    value = serializers.IntegerField()
    previous = serializers.IntegerField()
    changePercent = serializers.FloatField(allow_null=True)


class AnalyticsKpisSerializer(serializers.Serializer):
    revenue = MoneyKpiSerializer()
    orders = CountKpiSerializer()
    averageOrderValue = MoneyKpiSerializer(help_text="Charged sales before refunds / orders.")
    refunds = MoneyKpiSerializer()


class OrderStatusCountSerializer(serializers.Serializer):
    status = serializers.CharField()
    count = serializers.IntegerField()


class TopProductSerializer(serializers.Serializer):
    productId = serializers.CharField(allow_null=True)
    title = serializers.CharField()
    partNumber = serializers.CharField(allow_blank=True)
    units = serializers.IntegerField()
    revenue = serializers.FloatField(help_text="Unit price x quantity, without core or shipping.")


class QuoteFunnelSerializer(serializers.Serializer):
    created = serializers.IntegerField()
    sent = serializers.IntegerField(help_text="Emailed to the customer from the panel.")
    converted = serializers.IntegerField()
    conversionRate = serializers.FloatField(help_text="converted / created, as a percent.")


class CartFunnelSerializer(serializers.Serializer):
    created = serializers.IntegerField(help_text="Carts created in the range that still exist.")
    checkoutStarted = serializers.IntegerField(help_text="Storefront checkouts from a cart.")
    converted = serializers.IntegerField(help_text="Those checkouts that were paid.")
    abandoned = serializers.IntegerField(help_text="Carts abandoned now, last active in range.")


class DashboardAnalyticsSerializer(serializers.Serializer):
    range = serializers.ChoiceField(choices=["7d", "30d", "90d", "12m"])
    granularity = serializers.ChoiceField(choices=["day", "month"])
    timeZone = serializers.CharField()
    start = serializers.DateField()
    end = serializers.DateField()
    revenueSeries = RevenuePointSerializer(many=True)
    kpis = AnalyticsKpisSerializer()
    ordersByStatus = OrderStatusCountSerializer(many=True)
    topProducts = TopProductSerializer(many=True)
    quoteFunnel = QuoteFunnelSerializer()
    cartFunnel = CartFunnelSerializer()
