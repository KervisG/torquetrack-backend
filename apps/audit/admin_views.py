from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.admin_services import list_recent_activity
from apps.auth.authentication import SessionUserAuthentication
from apps.auth.permissions import HasTorqueTrackPermission, has_torquetrack_permission


class AdminActivityView(APIView):
    authentication_classes = [SessionUserAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "activity.view"

    def get(self, request):
        can_view_payment_ids = has_torquetrack_permission(request.user, "payments.transaction_id")
        return Response(list_recent_activity(can_view_payment_ids=can_view_payment_ids))
