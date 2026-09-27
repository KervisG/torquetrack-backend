"""Extensiones de drf-spectacular de `apps.customers`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

from apps.authorization.docs.schemas import ErrorResponseSerializer, OkResponseSerializer
from apps.customers.docs.schemas import (
    CustomerSerializer,
    MessageSerializer,
    PortalInviteRequestSerializer,
    RegisterRequestSerializer,
    TaxStatusRequestSerializer,
    TokenRequestSerializer,
)

ERR = OpenApiResponse(ErrorResponseSerializer)
CUSTOMER_ID = OpenApiParameter("customer_id", str, OpenApiParameter.PATH)


class RegisterViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.storefront.RegisterView"

    def view_replacement(self):
        class RegisterView(self.target_class):
            @extend_schema(
                operation_id="account_register",
                tags=["account"],
                summary="Register",
                description=(
                    "Public. Always answers the same 201, even when the email already exists."
                ),
                auth=[],
                request=RegisterRequestSerializer,
                responses={201: OpenApiResponse(MessageSerializer), 400: ERR, 429: ERR},
            )
            def post(self, request):
                return super().post(request)

        return RegisterView


class VerifyEmailViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.storefront.VerifyEmailView"

    def view_replacement(self):
        class VerifyEmailView(self.target_class):
            @extend_schema(
                operation_id="account_verify_email",
                tags=["account"],
                summary="Verify email",
                auth=[],
                request=TokenRequestSerializer,
                responses={200: OpenApiResponse(OkResponseSerializer), 400: ERR},
            )
            def post(self, request):
                return super().post(request)

        return VerifyEmailView


class ActivateAccountViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.storefront.ActivateAccountView"

    def view_replacement(self):
        class ActivateAccountView(self.target_class):
            @extend_schema(
                operation_id="account_activate",
                tags=["account"],
                summary="Activate an invited account",
                auth=[],
                request=TokenRequestSerializer,
                responses={200: OpenApiResponse(OkResponseSerializer), 400: ERR},
            )
            def post(self, request):
                return super().post(request)

        return ActivateAccountView


class AccountViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.storefront.AccountView"

    def view_replacement(self):
        @extend_schema_view(
            get=extend_schema(
                operation_id="account_read",
                tags=["account"],
                summary="Read the signed-in profile",
                responses={200: OpenApiResponse(CustomerSerializer), 401: ERR},
            ),
            patch=extend_schema(
                operation_id="account_update",
                tags=["account"],
                summary="Update the signed-in profile",
                request=CustomerSerializer,
                responses={200: OpenApiResponse(CustomerSerializer), 400: ERR, 401: ERR},
            ),
        )
        class AccountView(self.target_class):
            pass

        return AccountView


class AccountOrdersViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.storefront.AccountOrdersView"

    def view_replacement(self):
        class AccountOrdersView(self.target_class):
            @extend_schema(
                operation_id="account_orders",
                tags=["account"],
                summary="List the signed-in customer's orders",
                responses={200: OpenApiResponse(CustomerSerializer(many=True)), 401: ERR},
            )
            def get(self, request):
                return super().get(request)

        return AccountOrdersView


class AccountQuotesViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.storefront.AccountQuotesView"

    def view_replacement(self):
        class AccountQuotesView(self.target_class):
            @extend_schema(
                operation_id="account_quotes",
                tags=["account"],
                summary="List the signed-in customer's quotes",
                responses={200: OpenApiResponse(CustomerSerializer(many=True)), 401: ERR},
            )
            def get(self, request):
                return super().get(request)

        return AccountQuotesView


class AccountTaxExemptionViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.storefront.AccountTaxExemptionView"

    def view_replacement(self):
        class AccountTaxExemptionView(self.target_class):
            @extend_schema(
                operation_id="account_tax_exemption",
                tags=["account"],
                summary="Submit a tax exemption certificate",
                request=CustomerSerializer,
                responses={200: OpenApiResponse(OkResponseSerializer), 400: ERR, 401: ERR},
            )
            def post(self, request):
                return super().post(request)

        return AccountTaxExemptionView


class AdminCustomerListCreateViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.admin.AdminCustomerListCreateView"

    def view_replacement(self):
        @extend_schema_view(
            get=extend_schema(
                operation_id="admin_customers_list",
                tags=["admin: customers"],
                summary="List customers",
                description="Requires `customers.view`.",
                responses={200: OpenApiResponse(CustomerSerializer(many=True)), 403: ERR},
            ),
            post=extend_schema(
                operation_id="admin_customers_create",
                tags=["admin: customers"],
                summary="Create a customer",
                description="Requires `customers.edit`. Does not create a login.",
                request=CustomerSerializer,
                responses={201: OpenApiResponse(CustomerSerializer), 400: ERR, 403: ERR},
            ),
        )
        class AdminCustomerListCreateView(self.target_class):
            pass

        return AdminCustomerListCreateView


class AdminCustomerDeleteViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.admin.AdminCustomerDeleteView"

    def view_replacement(self):
        class AdminCustomerDeleteView(self.target_class):
            @extend_schema(
                operation_id="admin_customer_delete",
                tags=["admin: customers"],
                summary="Delete a customer",
                description="Requires `customers.delete`.",
                parameters=[CUSTOMER_ID],
                responses={200: OpenApiResponse(OkResponseSerializer), 403: ERR, 404: ERR},
            )
            def delete(self, request, customer_id):
                return super().delete(request, customer_id)

        return AdminCustomerDeleteView


class AdminCustomerTaxExemptionViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.admin.AdminCustomerTaxExemptionView"

    def view_replacement(self):
        class AdminCustomerTaxExemptionView(self.target_class):
            @extend_schema(
                operation_id="admin_customer_tax_exemption",
                tags=["admin: customers"],
                summary="Read a tax exemption",
                description="Requires `tax_exemptions.review`.",
                parameters=[CUSTOMER_ID],
                responses={200: OpenApiResponse(CustomerSerializer), 403: ERR, 404: ERR},
            )
            def get(self, request, customer_id):
                return super().get(request, customer_id)

        return AdminCustomerTaxExemptionView


class AdminCustomerTaxStatusViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.admin.AdminCustomerTaxStatusView"

    def view_replacement(self):
        class AdminCustomerTaxStatusView(self.target_class):
            @extend_schema(
                operation_id="admin_customer_tax_status",
                tags=["admin: customers"],
                summary="Set tax exemption status",
                description="Requires `tax_exemptions.review`.",
                parameters=[CUSTOMER_ID],
                request=TaxStatusRequestSerializer,
                responses={200: OpenApiResponse(CustomerSerializer), 400: ERR, 403: ERR},
            )
            def post(self, request, customer_id):
                return super().post(request, customer_id)

        return AdminCustomerTaxStatusView


class AdminCustomerPortalInviteViewExtension(OpenApiViewExtension):
    target_class = "apps.customers.views.admin.AdminCustomerPortalInviteView"

    def view_replacement(self):
        class AdminCustomerPortalInviteView(self.target_class):
            @extend_schema(
                operation_id="admin_customer_portal_invite",
                tags=["admin: customers"],
                summary="Invite a customer to the portal",
                description="Requires `customers.edit`.",
                request=PortalInviteRequestSerializer,
                responses={200: OpenApiResponse(MessageSerializer), 400: ERR, 403: ERR},
            )
            def post(self, request):
                return super().post(request)

        return AdminCustomerPortalInviteView
