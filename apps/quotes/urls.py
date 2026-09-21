from django.urls import path

from apps.quotes.admin_views import (
    QuoteConvertView,
    QuotePreviewView,
    QuoteReopenView,
    QuoteSendView,
)
from apps.quotes.pdf_views import PublicQuotePdfView
from apps.quotes.views import PublicQuoteCheckoutView, PublicQuoteView, QuoteRequestView

urlpatterns = [
    path("quote/request/", QuoteRequestView.as_view(), name="quote-request"),
    path("quote/public/<str:token>/", PublicQuoteView.as_view(), name="quote-public"),
    path("quote/public/<str:token>/pdf/", PublicQuotePdfView.as_view(), name="quote-public-pdf"),
    path(
        "quote/public/<str:token>/checkout/",
        PublicQuoteCheckoutView.as_view(),
        name="quote-public-checkout",
    ),
    path(
        "admin/quotes/<str:quote_id>/convert/",
        QuoteConvertView.as_view(),
        name="admin-quote-convert",
    ),
    path(
        "admin/quotes/<str:quote_id>/preview/",
        QuotePreviewView.as_view(),
        name="admin-quote-preview",
    ),
    path(
        "admin/quotes/<str:quote_id>/reopen/",
        QuoteReopenView.as_view(),
        name="admin-quote-reopen",
    ),
    path("admin/quotes/<str:quote_id>/send/", QuoteSendView.as_view(), name="admin-quote-send"),
]
