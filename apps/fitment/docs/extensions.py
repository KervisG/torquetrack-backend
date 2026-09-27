"""Extensión de drf-spectacular de `apps.fitment`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiResponse, extend_schema

from apps.authorization.docs.schemas import ErrorResponseSerializer
from apps.fitment.docs.schemas import FitmentCheckRequestSerializer, FitmentCheckSerializer


class FitmentCheckViewExtension(OpenApiViewExtension):
    target_class = "apps.fitment.views.FitmentCheckView"

    def view_replacement(self):
        class FitmentCheckView(self.target_class):
            @extend_schema(
                operation_id="fitment_check",
                tags=["storefront"],
                summary="Check cart fitment",
                description="Public. Compares the cart products with the decoded vehicle.",
                auth=[],
                request=FitmentCheckRequestSerializer,
                responses={
                    200: OpenApiResponse(FitmentCheckSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def post(self, request):
                return super().post(request)

        return FitmentCheckView
