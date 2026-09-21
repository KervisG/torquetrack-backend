"""`POST /api/shipping/rates` (task 7.5), matching
`app/api/shipping/rates/route.ts`.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shipping.services import get_shipping_rates


class ShippingRatesView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        payload, status = get_shipping_rates(body)
        return Response(payload, status=status)
