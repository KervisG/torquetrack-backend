"""Extensión de drf-spectacular de `apps.vin`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema

from apps.authorization.docs.schemas import ErrorResponseSerializer
from apps.vin.docs.schemas import VinDecodeSerializer


class VinDecodeViewExtension(OpenApiViewExtension):
    target_class = "apps.vin.views.VinDecodeView"

    def view_replacement(self):
        class VinDecodeView(self.target_class):
            @extend_schema(
                operation_id="vin_decode",
                tags=["storefront"],
                summary="Decode a VIN",
                description="Public. `vin` is the 17-character vehicle identification number.",
                auth=[],
                parameters=[OpenApiParameter("vin", str, OpenApiParameter.QUERY, required=True)],
                responses={
                    200: OpenApiResponse(VinDecodeSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                    502: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def get(self, request):
                return super().get(request)

        return VinDecodeView
