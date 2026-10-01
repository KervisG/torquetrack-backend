"""Extensión de drf-spectacular de `apps.tax`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiResponse, extend_schema

from apps.authorization.docs.examples import error_example
from apps.authorization.docs.schemas import ErrorResponseSerializer
from apps.common.us_addresses import (
    INVALID_SHIPPING_STATE,
    SHIPPING_STATE_REQUIRED,
    ZIP_STATE_MISMATCH,
)
from apps.tax.docs.schemas import TaxEstimateRequestSerializer, TaxEstimateSerializer


class TaxEstimateViewExtension(OpenApiViewExtension):
    target_class = "apps.tax.views.TaxEstimateView"

    def view_replacement(self):
        class TaxEstimateView(self.target_class):
            @extend_schema(
                operation_id="tax_estimate",
                tags=["storefront"],
                summary="Estimate sales tax",
                description=(
                    "Public. A signed-in customer with a verified exemption is charged 0. "
                    "Otherwise `state` is required and must be a valid US code (400 if it "
                    "is missing or unknown); tax is charged only for the nexus states. "
                    "TaxJar is used when configured; otherwise the state fallback table."
                ),
                auth=[],
                request=TaxEstimateRequestSerializer,
                responses={
                    200: OpenApiResponse(TaxEstimateSerializer),
                    400: OpenApiResponse(
                        ErrorResponseSerializer,
                        examples=[
                            error_example("Shipping state missing", SHIPPING_STATE_REQUIRED),
                            error_example("Shipping state invalid", INVALID_SHIPPING_STATE),
                            error_example("ZIP from another state", ZIP_STATE_MISMATCH),
                        ],
                    ),
                },
            )
            def post(self, request):
                return super().post(request)

        return TaxEstimateView
