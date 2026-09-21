from django.urls import path

from apps.vin.views import VinDecodeView

urlpatterns = [
    path("vin/decode/", VinDecodeView.as_view(), name="vin-decode"),
]
