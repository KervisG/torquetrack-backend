"""Extensión de drf-spectacular de `apps.health`: reemplaza la view por una
subclase con `@extend_schema` solo al generar el esquema."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema

from apps.health.docs.schemas import (
    HealthOkResponseSerializer,
    HealthUnavailableResponseSerializer,
)


class HealthViewExtension(OpenApiViewExtension):
    target_class = "apps.health.views.HealthView"

    def view_replacement(self):
        class HealthView(self.target_class):
            @extend_schema(
                operation_id="health_check",
                tags=["platform"],
                summary="Health check",
                description=(
                    "Public, no session and not throttled. Answers `200` when the "
                    "database accepts connections and `503` when it does not. Exempt "
                    "from the HTTPS redirect in production so plain HTTP probes work."
                ),
                auth=[],
                responses={
                    200: OpenApiResponse(
                        HealthOkResponseSerializer,
                        examples=[OpenApiExample("Healthy", value={"ok": True})],
                    ),
                    503: OpenApiResponse(
                        HealthUnavailableResponseSerializer,
                        examples=[
                            OpenApiExample(
                                "Database down",
                                value={"ok": False, "error": "Database unavailable"},
                            )
                        ],
                    ),
                },
            )
            def get(self, request):
                return super().get(request)

        return HealthView
