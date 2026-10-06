from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.permissions import HasRolePermission
from apps.dashboard.services import get_dashboard_analytics, get_dashboard_counts
from config.responses import service_response


class AdminDashboardView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "dashboard.view"

    def get(self, request):
        return Response(get_dashboard_counts())


class AdminDashboardAnalyticsView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "dashboard.view"

    def get(self, request):
        return service_response(get_dashboard_analytics(request.query_params.get("range")))
