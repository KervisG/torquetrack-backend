from django.urls import path

from apps.checkout.views import (
    AdminOrderDetailView,
    AdminOrderFulfillmentView,
    AdminOrderPaymentLinkView,
    AdminOrderRefundsView,
    AdminOrdersListView,
    AdminOrderTakePaymentView,
    CheckoutView,
    StripeWebhookView,
)

urlpatterns = [
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("webhooks/stripe/", StripeWebhookView.as_view(), name="stripe-webhook"),
    path("admin/orders/", AdminOrdersListView.as_view(), name="admin-orders-list"),
    path(
        "admin/orders/<str:order_id>/",
        AdminOrderDetailView.as_view(),
        name="admin-order-detail",
    ),
    path(
        "admin/orders/<str:order_id>/fulfillment/",
        AdminOrderFulfillmentView.as_view(),
        name="admin-order-fulfillment",
    ),
    path(
        "admin/orders/<str:order_id>/payment-link/",
        AdminOrderPaymentLinkView.as_view(),
        name="admin-order-payment-link",
    ),
    path(
        "admin/orders/<str:order_id>/refunds/",
        AdminOrderRefundsView.as_view(),
        name="admin-order-refunds",
    ),
    path(
        "admin/orders/<str:order_id>/take-payment/",
        AdminOrderTakePaymentView.as_view(),
        name="admin-order-take-payment",
    ),
]
