"""Extensión de drf-spectacular de `apps.dashboard`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiResponse, extend_schema

from apps.authorization.docs.schemas import ErrorResponseSerializer
from apps.dashboard.docs.schemas import DashboardSerializer


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
