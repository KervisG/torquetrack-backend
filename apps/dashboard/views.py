from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.permissions import HasRolePermission
from apps.dashboard.services import get_dashboard_counts


class AdminDashboardView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "dashboard.view"

    def get(self, request):
        return Response(get_dashboard_counts())
