"""Extensión de drf-spectacular de `apps.shipping`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiResponse, extend_schema

from apps.authorization.docs.schemas import ErrorResponseSerializer
from apps.shipping.docs.schemas import ShippingRatesRequestSerializer, ShippingRatesSerializer


class ShippingRatesViewExtension(OpenApiViewExtension):
    target_class = "apps.shipping.views.ShippingRatesView"

    def view_replacement(self):
        class ShippingRatesView(self.target_class):
            @extend_schema(
                operation_id="shipping_rates",
                tags=["storefront"],
                summary="Quote shipping rates",
                description="Public. Rates come from EasyPost when it is configured.",
                auth=[],
                request=ShippingRatesRequestSerializer,
                responses={
                    200: OpenApiResponse(ShippingRatesSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    502: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def post(self, request):
                return super().post(request)

        return ShippingRatesView
