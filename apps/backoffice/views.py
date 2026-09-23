"""`GET /api/admin/dashboard` and `GET /api/admin/activity` (task 7.1),
matching `app/api/admin/dashboard/route.ts` and
`app/api/admin/activity/route.ts`.
"""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.authentication import SessionUserAuthentication
from apps.auth.permissions import HasTorqueTrackPermission
from apps.backoffice.services import get_dashboard_counts, list_recent_activity


class AdminDashboardView(APIView):
    authentication_classes = [SessionUserAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "dashboard.view"

    def get(self, request):
        return Response(get_dashboard_counts())


class AdminActivityView(APIView):
    authentication_classes = [SessionUserAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "activity.view"

    def get(self, request):
        return Response(list_recent_activity())
