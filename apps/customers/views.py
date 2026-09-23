"""Endpoints públicos del cliente: autoservicio en `/api/account/**` y la
activación del portal en `/api/activate/`.

El autoservicio exige una sesión (401) con un `Customer` vinculado (404).
Los endpoints de staff viven en `admin_views.py`.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.authentication import SessionUserAuthentication
from apps.auth.models import User
from apps.auth.services import serialize_session_user
from apps.auth.sessions import csrf_token_payload, start_user_session
from apps.auth.utils.throttling import ActivateRateThrottle
from apps.customers.services import (
    activate_customer_account,
    customer_for_user,
    list_account_orders,
    list_account_quotes,
    serialize_account,
    submit_tax_exemption,
    update_account,
)


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _error(result: dict) -> Response:
    return Response({"error": result["error"]}, status=result.get("status", 400))


class _AccountView(APIView):
    authentication_classes = [SessionUserAuthentication]
    permission_classes = [AllowAny]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.customer = None
        if isinstance(request.user, User):
            self.customer = customer_for_user(request.user)

    def _denied(self, request):
        """Devuelve `None` si hay perfil, o el `Response` de error."""
        if not isinstance(request.user, User):
            return Response({"error": "Unauthorized"}, status=401)
        if self.customer is None:
            return Response({"error": "Customer profile not found"}, status=404)
        return None


class AccountView(_AccountView):
    """`GET/PATCH /api/account/`."""

    def get(self, request):
        denied = self._denied(request)
        if denied is not None:
            return denied
        return Response({"customer": serialize_account(self.customer)})

    def patch(self, request):
        denied = self._denied(request)
        if denied is not None:
            return denied
        result = update_account(self.customer, _body(request))
        if "error" in result:
            return _error(result)
        return Response(result)


class AccountOrdersView(_AccountView):
    """`GET /api/account/orders/`."""

    def get(self, request):
        denied = self._denied(request)
        if denied is not None:
            return denied
        return Response(list_account_orders(self.customer))


class AccountQuotesView(_AccountView):
    """`GET /api/account/quotes/`."""

    def get(self, request):
        denied = self._denied(request)
        if denied is not None:
            return denied
        return Response(list_account_quotes(self.customer))


class AccountTaxExemptionView(_AccountView):
    """`POST /api/account/tax-exemption/`."""

    def post(self, request):
        denied = self._denied(request)
        if denied is not None:
            return denied
        result = submit_tax_exemption(self.customer, _body(request))
        if "error" in result:
            return _error(result)
        return Response(result)


class ActivateAccountView(APIView):
    """`POST /api/activate/` — `{token, password}` del enlace de invitación."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ActivateRateThrottle]

    def post(self, request):
        result = activate_customer_account(_body(request))
        if "error" in result:
            return _error(result)
        start_user_session(request, result["user"])
        return Response(
            {
                "authenticated": True,
                "user": serialize_session_user(result["user"]),
                **csrf_token_payload(request),
            },
            status=201,
        )
