from django.urls import path

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
]
