from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.fitment.services import check_cart_fitment


class FitmentCheckView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        vehicle = request.data.get("vehicle")
        if vehicle is None:
            return Response({"error": "Vehicle required"}, status=400)

        payload, status = check_cart_fitment(request.data.get("items"), vehicle)
        return Response(payload, status=status)
