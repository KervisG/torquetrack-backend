"""Extensiones de drf-spectacular de `apps.dashboard`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema

from apps.authorization.docs.schemas import ErrorResponseSerializer
from apps.dashboard.docs.schemas import DashboardAnalyticsSerializer, DashboardSerializer
from apps.dashboard.services import ANALYTICS_RANGES, DEFAULT_ANALYTICS_RANGE, INVALID_RANGE


class AdminDashboardViewExtension(OpenApiViewExtension):
    target_class = "apps.dashboard.views.AdminDashboardView"

    def view_replacement(self):
        class AdminDashboardView(self.target_class):
            @extend_schema(
                operation_id="admin_dashboard",
                tags=["admin: dashboard"],
                summary="Dashboard counts",
                description="Requires `dashboard.view`. Counts are read-only.",
                responses={
                    200: OpenApiResponse(DashboardSerializer),
                    401: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def get(self, request):
                return super().get(request)

        return AdminDashboardView


class AdminDashboardAnalyticsViewExtension(OpenApiViewExtension):
    target_class = "apps.dashboard.views.AdminDashboardAnalyticsView"

    def view_replacement(self):
        class AdminDashboardAnalyticsView(self.target_class):
            @extend_schema(
                operation_id="admin_dashboard_analytics",
                tags=["admin: dashboard"],
                summary="Dashboard analytics",
                description=(
                    "Requires `dashboard.view`. Read-only aggregates for the range: revenue "
                    "series (zero-filled; daily, or monthly with `12m`), KPIs against the "
                    "previous period of equal length, orders by status, top 10 products, "
                    "and the quote and cart funnels. Revenue matches `salesToday`: charged "
                    "payments by payment date, without tax, minus succeeded refunds. Days "
                    "are cut in the store time zone (`timeZone`, `STORE_TIME_ZONE`)."
                ),
                parameters=[
                    OpenApiParameter(
                        "range",
                        str,
                        OpenApiParameter.QUERY,
                        enum=list(ANALYTICS_RANGES),
                        default=DEFAULT_ANALYTICS_RANGE,
                    )
                ],
                responses={
                    200: OpenApiResponse(DashboardAnalyticsSerializer),
                    400: OpenApiResponse(
                        ErrorResponseSerializer,
                        examples=[
                            OpenApiExample(
                                "Invalid range",
                                value={"error": INVALID_RANGE},
                                status_codes=["400"],
                            )
                        ],
                    ),
                    401: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def get(self, request):
                return super().get(request)

        return AdminDashboardAnalyticsView
