"""Extensión de drf-spectacular de `apps.tax`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiResponse, extend_schema

from apps.authorization.docs.schemas import ErrorResponseSerializer
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
                    "TaxJar is used when configured; otherwise the state fallback table."
                ),
                auth=[],
                request=TaxEstimateRequestSerializer,
                responses={
                    200: OpenApiResponse(TaxEstimateSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def post(self, request):
                return super().post(request)

        return TaxEstimateView
