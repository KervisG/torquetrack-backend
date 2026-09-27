"""`tax-exemption` (GET) devuelve el tax ID completo y el certificado, y
`tax-status` (POST) deja al cliente comprar sin impuestos: por eso los dos
exigen `tax_exemptions.review`."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.permissions import (
    HasRolePermission,
    has_role_permission,
    is_staff_user,
)
from apps.customers.services import (
    create_portal_invite,
    delete_admin_customer,
    get_customer_tax_exemption,
    list_admin_customers,
    update_customer_tax_status,
    upsert_admin_customer,
)


class AdminCustomerListCreateView(APIView):
    permission_classes = [HasRolePermission]

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
    permission_classes = [HasRolePermission]
    required_permission = "customers.delete"

    def delete(self, request, customer_id):
        result = delete_admin_customer(customer_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminCustomerTaxExemptionView(APIView):
    required_permission = "tax_exemptions.review"

    def get(self, request, customer_id):
        if not is_staff_user(request.user):
            return Response({"error": "Unauthorized"}, status=401)
        if not has_role_permission(request.user, self.required_permission):
            return Response({"error": "Forbidden"}, status=403)

        result = get_customer_tax_exemption(customer_id)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminCustomerTaxStatusView(APIView):
    required_permission = "tax_exemptions.review"

    def post(self, request, customer_id):
        if not is_staff_user(request.user):
            return Response({"error": "Unauthorized"}, status=401)
        if not has_role_permission(request.user, self.required_permission):
            return Response({"error": "Forbidden"}, status=403)

        body = request.data if isinstance(request.data, dict) else {}
        result = update_customer_tax_status(customer_id, body, request.user.email)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminCustomerPortalInviteView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "customers.edit"

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        result = create_portal_invite(body)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)
