from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.authentication.utils.throttling import VinDecodeRateThrottle
from apps.vin.services import decode_vehicle
from config.responses import service_response


class VinDecodeView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [VinDecodeRateThrottle]

    def get(self, request):
        return service_response(decode_vehicle(request.query_params.get("vin")))
