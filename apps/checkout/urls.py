from django.urls import path

from apps.checkout.views import (
    AdminOrderDetailView,
    AdminOrderFulfillmentView,
    AdminOrderNotesView,
    AdminOrderPaymentLinkView,
    AdminOrderRefundsView,
    AdminOrdersListView,
    AdminOrderTakePaymentView,
    AuthorizeNetWebhookView,
    CheckoutView,
    PaymentPageView,
)

urlpatterns = [
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path(
        "webhooks/authorize-net/",
        AuthorizeNetWebhookView.as_view(),
        name="authorize-net-webhook",
    ),
    path("payments/<str:payment_id>/pay/", PaymentPageView.as_view(), name="payment-page"),
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
        "admin/orders/<str:order_id>/notes/",
        AdminOrderNotesView.as_view(),
        name="admin-order-notes",
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
