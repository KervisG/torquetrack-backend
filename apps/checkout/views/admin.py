"""`PATCH`/`DELETE` no usan `HasRolePermission`: el permiso exigido
depende del campo que cambia, así que la sesión de staff (401) y cada permiso
(403) se chequean por separado."""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.permissions import (
    HasRolePermission,
    has_role_permission,
    is_staff_user,
)
from apps.checkout.models import OrderStatus
from apps.checkout.services import (
    create_admin_payment_link,
    delete_admin_order,
    list_admin_orders,
    patch_admin_order,
    refund_order,
    take_admin_payment,
    update_order_fulfillment,
)
from config.responses import service_response


class AdminOrdersListView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "orders.view"

    def get(self, request):
        can_view_ids = has_role_permission(request.user, "payments.transaction_id")
        return Response(list_admin_orders(can_view_transaction_ids=can_view_ids))


class AdminOrderDetailView(APIView):
    # Abierta a propósito: la view separa el 401 (sin sesión de staff) del 403
    # (sin el permiso que pide cada campo); `HasRolePermission` los colapsaría.
    permission_classes = [AllowAny]

    def patch(self, request, order_id):
        user = request.user
        if not is_staff_user(user):
            return Response({"error": "Unauthorized"}, status=401)

        body = request.data if isinstance(request.data, dict) else {}

        status_value = body.get("status")
        if status_value:
            is_cancel = str(status_value).upper() == OrderStatus.CANCELLED
            required = "orders.cancel" if is_cancel else "orders.status"
            if not has_role_permission(user, required):
                return Response({"error": "Forbidden"}, status=403)

        workflow = body.get("workflow")
        if isinstance(workflow, dict):
            if workflow.get("coreCase") and not has_role_permission(user, "cores.manage"):
                return Response({"error": "Forbidden"}, status=403)
            if workflow.get("returnCase") and not has_role_permission(
                user, "returns.manage"
            ):
                return Response({"error": "Forbidden"}, status=403)

        result = patch_admin_order(order_id, body, user.email)
        return service_response(result)

    def delete(self, request, order_id):
        user = request.user
        if not is_staff_user(user):
            return Response({"error": "Unauthorized"}, status=401)
        if not has_role_permission(user, "orders.cancel"):
            return Response({"error": "Forbidden"}, status=403)

        result = delete_admin_order(order_id, user.email)
        return service_response(result)


class AdminOrderPaymentLinkView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "payments.take"

    def post(self, request, order_id):
        result = create_admin_payment_link(order_id)
        return service_response(result)


class AdminOrderTakePaymentView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "payments.take"

    def post(self, request, order_id):
        result = take_admin_payment(order_id, request.user.email)
        return service_response(result)


class AdminOrderRefundsView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "payments.refund"

    def post(self, request, order_id):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(
            refund_order(
                order_id,
                body,
                request.user.email,
                can_view_transaction_ids=has_role_permission(
                    request.user, "payments.transaction_id"
                ),
            )
        )


class AdminOrderFulfillmentView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "orders.status"

    def post(self, request, order_id):
        return service_response(
            update_order_fulfillment(order_id, request.data, request.user.email)
        )
