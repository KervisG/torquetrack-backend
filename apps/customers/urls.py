from django.urls import path

from apps.customers.admin_views import (
    AdminCustomerDeleteView,
    AdminCustomerListCreateView,
    AdminCustomerPortalInviteView,
    AdminCustomerTaxExemptionView,
    AdminCustomerTaxStatusView,
)
from apps.customers.views import (
    AccountOrdersView,
    AccountQuotesView,
    AccountTaxExemptionView,
    AccountView,
    ActivateAccountView,
    RegisterView,
    VerifyEmailView,
)

urlpatterns = [
    path("account/", AccountView.as_view(), name="account"),
    path("account/orders/", AccountOrdersView.as_view(), name="account-orders"),
    path("account/quotes/", AccountQuotesView.as_view(), name="account-quotes"),
    path(
        "account/tax-exemption/",
        AccountTaxExemptionView.as_view(),
        name="account-tax-exemption",
    ),
    path("register/", RegisterView.as_view(), name="register"),
    path("verify-email/", VerifyEmailView.as_view(), name="verify-email"),
    path("activate/", ActivateAccountView.as_view(), name="activate"),
    path(
        "admin/customers/",
        AdminCustomerListCreateView.as_view(),
        name="admin-customers-list-create",
    ),
    path(
        "admin/customers/portal-invite/",
        AdminCustomerPortalInviteView.as_view(),
        name="admin-customer-portal-invite",
    ),
    path(
        "admin/customers/<str:customer_id>/",
        AdminCustomerDeleteView.as_view(),
        name="admin-customer-delete",
    ),
    path(
        "admin/customers/<str:customer_id>/tax-exemption/",
        AdminCustomerTaxExemptionView.as_view(),
        name="admin-customer-tax-exemption",
    ),
    path(
        "admin/customers/<str:customer_id>/tax-status/",
        AdminCustomerTaxStatusView.as_view(),
        name="admin-customer-tax-status",
    ),
]
