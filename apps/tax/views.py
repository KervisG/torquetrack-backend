"""La sesión es opcional, como en el checkout: sin ella es un invitado y con
ella se exige CSRF."""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.authentication import SessionUserAuthentication
from apps.tax.services import estimate_tax


class TaxEstimateView(APIView):
    authentication_classes = [SessionUserAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return Response(estimate_tax(body, request.user))
