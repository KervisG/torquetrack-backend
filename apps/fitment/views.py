from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.fitment.services import check_cart_fitment
from config.responses import service_response


class FitmentCheckView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        vehicle = request.data.get("vehicle")
        if vehicle is None:
            return Response({"error": "Vehicle required"}, status=400)

        return service_response(check_cart_fitment(request.data.get("items"), vehicle))
