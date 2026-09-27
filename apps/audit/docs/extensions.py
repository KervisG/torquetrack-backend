"""Extensión de drf-spectacular de `apps.audit`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema

from apps.audit.docs.schemas import ActivityPageSerializer, ErrorResponseSerializer


class AdminActivityViewExtension(OpenApiViewExtension):
    target_class = "apps.audit.views.AdminActivityView"

    def view_replacement(self):
        class AdminActivityView(self.target_class):
            @extend_schema(
                operation_id="admin_activity_list",
                tags=["admin: activity"],
                summary="List activity",
                description=(
                    "Requires `activity.view`. Newest first. Stripe ids inside `data` are "
                    "omitted unless the caller has `payments.transaction_id`."
                ),
                parameters=[
                    OpenApiParameter("limit", int, OpenApiParameter.QUERY, required=False),
                    OpenApiParameter(
                        "before",
                        int,
                        OpenApiParameter.QUERY,
                        required=False,
                        description="`nextCursor` from the previous page.",
                    ),
                ],
                responses={
                    200: OpenApiResponse(ActivityPageSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    401: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def get(self, request):
                return super().get(request)

        return AdminActivityView
