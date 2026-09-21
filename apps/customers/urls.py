from django.urls import path

from apps.customers.views import (
    AdminCustomerDeleteView,
    AdminCustomerListCreateView,
    AdminCustomerPortalInviteView,
    AdminCustomerTaxExemptionView,
    AdminCustomerTaxStatusView,
)

urlpatterns = [
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
