from django.contrib.auth import login
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import User
from apps.authentication.services import csrf_token_payload, serialize_session_user
from apps.authentication.utils.throttling import (
    ActivateRateThrottle,
    RegisterRateThrottle,
    VerifyEmailRateThrottle,
)
from apps.customers.services import (
    activate_customer_account,
    customer_for_user,
    list_account_orders,
    list_account_quotes,
    register_customer,
    serialize_account,
    submit_tax_exemption,
    update_account,
    verify_customer_email,
)
from config.responses import service_response


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _signed_in(request, user: User) -> Response:
    """Abre la sesión y responde con la misma forma que `/api/session/`."""
    login(request, user)
    return Response(
        {
            "authenticated": True,
            "user": serialize_session_user(user),
            **csrf_token_payload(request),
        },
        status=201,
    )


class RegisterView(APIView):
    # Solo JSON: un formulario de otro sitio no puede mandar `application/json`
    # sin preflight de CORS, así que no llega a esta ruta sin CSRF (415).
    parser_classes = [JSONParser]
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [RegisterRateThrottle]

    def post(self, request):
        # Sin `login()`: la respuesta es la misma exista o no la cuenta.
        return service_response(register_customer(_body(request)), success_status=201)


class VerifyEmailView(APIView):
    """Público: el token del correo es la prueba, así funciona aunque el enlace
    se abra en otro navegador sin sesión."""

    parser_classes = [JSONParser]
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [VerifyEmailRateThrottle]

    def post(self, request):
        return service_response(verify_customer_email(_body(request)))


class _AccountView(APIView):
    permission_classes = [AllowAny]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.customer = None
        if request.user.is_authenticated:
            self.customer = customer_for_user(request.user)

    def _denied(self, request):
        """Devuelve `None` si hay perfil, o el `Response` de error."""
        if not request.user.is_authenticated:
            return Response({"error": "Unauthorized"}, status=401)
        if self.customer is None:
            return Response({"error": "Customer profile not found"}, status=404)
        return None


class AccountView(_AccountView):
    def get(self, request):
        denied = self._denied(request)
        if denied is not None:
            return denied
        return Response({"customer": serialize_account(self.customer)})

    def patch(self, request):
        denied = self._denied(request)
        if denied is not None:
            return denied
        return service_response(update_account(self.customer, _body(request)))


class AccountOrdersView(_AccountView):
    def get(self, request):
        denied = self._denied(request)
        if denied is not None:
            return denied
        return Response(list_account_orders(self.customer))


class AccountQuotesView(_AccountView):
    def get(self, request):
        denied = self._denied(request)
        if denied is not None:
            return denied
        return Response(list_account_quotes(self.customer))


class AccountTaxExemptionView(_AccountView):
    def post(self, request):
        denied = self._denied(request)
        if denied is not None:
            return denied
        return service_response(submit_tax_exemption(self.customer, _body(request)))


class ActivateAccountView(APIView):
    parser_classes = [JSONParser]
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ActivateRateThrottle]

    def post(self, request):
        result = activate_customer_account(_body(request))
        if "error" in result:
            return service_response(result)
        return _signed_in(request, result["user"])
