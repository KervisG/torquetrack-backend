from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import list_activity_page
from apps.authorization.permissions import HasRolePermission, has_role_permission


class AdminActivityView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "activity.view"

    def get(self, request):
        can_view_payment_ids = has_role_permission(request.user, "payments.transaction_id")
        data, status = list_activity_page(
            request.query_params.get("limit"),
            request.query_params.get("before"),
            can_view_payment_ids=can_view_payment_ids,
        )
        return Response(data, status=status)
