"""`POST /api/tax/estimate` (task 7.5), matching
`app/api/tax/estimate/route.ts`.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tax.services import estimate_tax


class TaxEstimateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return Response(estimate_tax(body))
