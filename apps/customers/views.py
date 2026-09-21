"""`admin/customers` views (task 7.2), matching the route files documented
in `apps/customers/services.py`.

`tax-exemption` (GET) and `tax-status` (POST) intentionally do NOT use
`HasTorqueTrackPermission` — the legacy routes gate on `requireAdmin()`
alone (any active admin-role-or-employee session, 401-only), not a
specific permission string. See the test module's docstring.
"""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import AdminSessionAuthentication
from apps.accounts.permissions import HasTorqueTrackPermission, is_active_admin_user
from apps.customers.services import (
    create_portal_invite,
    delete_admin_customer,
    get_customer_tax_exemption,
    list_admin_customers,
    update_customer_tax_status,
    upsert_admin_customer,
)


class AdminCustomerListCreateView(APIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [HasTorqueTrackPermission]

    @property
    def required_permission(self):
        return "customers.edit" if self.request.method == "POST" else "customers.view"

    def get(self, request):
        return Response(list_admin_customers())

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        result = upsert_admin_customer(body)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminCustomerDeleteView(APIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "customers.delete"

    def delete(self, request, customer_id):
        result = delete_admin_customer(customer_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminCustomerTaxExemptionView(APIView):
    authentication_classes = [AdminSessionAuthentication]

    def get(self, request, customer_id):
        if not is_active_admin_user(request.user):
            return Response({"error": "Unauthorized"}, status=401)

        result = get_customer_tax_exemption(customer_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminCustomerTaxStatusView(APIView):
    authentication_classes = [AdminSessionAuthentication]

    def post(self, request, customer_id):
        if not is_active_admin_user(request.user):
            return Response({"error": "Unauthorized"}, status=401)

        body = request.data if isinstance(request.data, dict) else {}
        result = update_customer_tax_status(customer_id, body, request.user.username)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminCustomerPortalInviteView(APIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [HasTorqueTrackPermission]
    required_permission = "customers.edit"

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        result = create_portal_invite(body)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)
