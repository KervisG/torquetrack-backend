"""La sesión es opcional, como en el checkout: sin ella es un invitado y con
ella se exige CSRF."""
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.authentication.utils.throttling import TaxEstimateRateThrottle
from apps.tax.services import estimate_tax
from config.responses import service_response


class TaxEstimateView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [TaxEstimateRateThrottle]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(estimate_tax(body, request.user))
