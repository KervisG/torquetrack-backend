from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.shipping.services import get_shipping_rates
from config.responses import service_response


class ShippingRatesView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(get_shipping_rates(body))
