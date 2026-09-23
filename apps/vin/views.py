from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.vin.services import decode_vehicle


class VinDecodeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        data, status = decode_vehicle(request.query_params.get("vin"))
        return Response(data, status=status)
