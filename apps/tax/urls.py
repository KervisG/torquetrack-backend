from django.urls import path

from apps.tax.views import TaxEstimateView

urlpatterns = [
    path("tax/estimate/", TaxEstimateView.as_view(), name="tax-estimate"),
]
