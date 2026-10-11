from django.urls import path

from apps.quotes.views import (
    AdminQuoteListCreateView,
    AdminQuoteTaxView,
    AdminQuoteVinView,
    PublicQuoteCheckoutView,
    PublicQuoteDetailsView,
    PublicQuotePdfView,
    QuoteConvertView,
    QuoteDeleteView,
    QuotePreviewView,
    QuoteReopenView,
    QuoteRequestView,
    QuoteSendView,
)

urlpatterns = [
    path("quote/request/", QuoteRequestView.as_view(), name="quote-request"),
    path("quote/public/<str:token>/pdf/", PublicQuotePdfView.as_view(), name="quote-public-pdf"),
    path(
        "quote/public/<str:token>/details/",
        PublicQuoteDetailsView.as_view(),
        name="quote-public-details",
    ),
    path(
        "quote/public/<str:token>/checkout/",
        PublicQuoteCheckoutView.as_view(),
        name="quote-public-checkout",
    ),
    path("admin/quotes/", AdminQuoteListCreateView.as_view(), name="admin-quotes-list-create"),
    path("admin/quotes/vin/", AdminQuoteVinView.as_view(), name="admin-quote-vin"),
    path("admin/quotes/tax/", AdminQuoteTaxView.as_view(), name="admin-quote-tax"),
    path(
        "admin/quotes/<str:quote_id>/",
        QuoteDeleteView.as_view(),
        name="admin-quote-delete",
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
