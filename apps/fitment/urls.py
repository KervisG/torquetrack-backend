from django.urls import path

from apps.fitment.views import FitmentCheckView

urlpatterns = [
    path("fitment/check/", FitmentCheckView.as_view(), name="fitment-check"),
]
