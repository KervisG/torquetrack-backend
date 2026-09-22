"""`admin/orders` views (task 7.4), matching the route files documented in
`apps/checkout/admin_services.py`.

`PATCH`/`DELETE` intentionally do NOT use `HasTorqueTrackPermission` — the
legacy routes gate on `requireAdmin()` (401) plus one or more
per-field `hasPermission()` checks (403), not a single static
`required_permission`. See the test module's docstring.
"""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import (
    HasTorqueTrackPermission,
    has_torquetrack_permission,
    is_active_admin_user,
)
from apps.auth.authentication import AdminSessionAuthentication
from apps.checkout.admin_services import (
    create_admin_payment_link,
    delete_admin_order,
    list_admin_orders,
    patch_admin_order,
    take_admin_payment,
)


class AdminOrdersListView(APIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "orders.view"

    def get(self, request):
        return Response(list_admin_orders())


class AdminOrderDetailView(APIView):
    authentication_classes = [AdminSessionAuthentication]

    def patch(self, request, order_id):
        user = request.user
        if not is_active_admin_user(user):
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

        result = patch_admin_order(order_id, body, user.username)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)

    def delete(self, request, order_id):
        user = request.user
        if not is_active_admin_user(user):
            return Response({"error": "Unauthorized"}, status=401)
        if not has_torquetrack_permission(user, "orders.cancel"):
            return Response({"error": "Forbidden"}, status=403)

        result = delete_admin_order(order_id, user.username)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminOrderPaymentLinkView(APIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "payments.take"

    def post(self, request, order_id):
        result = create_admin_payment_link(order_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminOrderTakePaymentView(APIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "payments.take"

    def post(self, request, order_id):
        result = take_admin_payment(order_id, request.user.username)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)
