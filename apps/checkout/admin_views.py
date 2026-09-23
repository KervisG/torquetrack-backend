"""`PATCH`/`DELETE` no usan `HasTorqueTrackPermission`: el permiso exigido
depende del campo que cambia, así que la sesión de staff (401) y cada permiso
(403) se chequean por separado."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.authentication import SessionUserAuthentication
from apps.auth.permissions import (
    HasTorqueTrackPermission,
    has_torquetrack_permission,
    is_staff_user,
)
from apps.checkout.admin_services import (
    create_admin_payment_link,
    delete_admin_order,
    list_admin_orders,
    patch_admin_order,
    take_admin_payment,
)


class AdminOrdersListView(APIView):
    authentication_classes = [SessionUserAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "orders.view"

    def get(self, request):
        return Response(list_admin_orders())


class AdminOrderDetailView(APIView):
    authentication_classes = [SessionUserAuthentication]

    def patch(self, request, order_id):
        user = request.user
        if not is_staff_user(user):
            return Response({"error": "Unauthorized"}, status=401)

        body = request.data if isinstance(request.data, dict) else {}

        status_value = body.get("status")
        if status_value:
            is_cancel = str(status_value).upper() == "CANCELLED"
            required = "orders.cancel" if is_cancel else "orders.status"
            if not has_torquetrack_permission(user, required):
                return Response({"error": "Forbidden"}, status=403)

        workflow = body.get("workflow")
        if isinstance(workflow, dict):
            if workflow.get("coreCase") and not has_torquetrack_permission(user, "cores.manage"):
                return Response({"error": "Forbidden"}, status=403)
            if workflow.get("returnCase") and not has_torquetrack_permission(
                user, "returns.manage"
            ):
                return Response({"error": "Forbidden"}, status=403)

        result = patch_admin_order(order_id, body, user.email)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)

    def delete(self, request, order_id):
        user = request.user
        if not is_staff_user(user):
            return Response({"error": "Unauthorized"}, status=401)
        if not has_torquetrack_permission(user, "orders.cancel"):
            return Response({"error": "Forbidden"}, status=403)

        result = delete_admin_order(order_id, user.email)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminOrderPaymentLinkView(APIView):
    authentication_classes = [SessionUserAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "payments.take"

    def post(self, request, order_id):
        result = create_admin_payment_link(order_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminOrderTakePaymentView(APIView):
    authentication_classes = [SessionUserAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "payments.take"

    def post(self, request, order_id):
        result = take_admin_payment(order_id, request.user.email)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)
