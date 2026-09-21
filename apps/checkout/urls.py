from django.urls import path

from apps.checkout.views import CheckoutView
from apps.checkout.webhook_views import StripeWebhookView

urlpatterns = [
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("webhooks/stripe/", StripeWebhookView.as_view(), name="stripe-webhook"),
]
