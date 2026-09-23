from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.authentication import SessionUserAuthentication
from apps.auth.permissions import HasTorqueTrackPermission
from apps.dashboard.admin_services import get_dashboard_counts


class AdminDashboardView(APIView):
    authentication_classes = [SessionUserAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "dashboard.view"

    def get(self, request):
        return Response(get_dashboard_counts())
