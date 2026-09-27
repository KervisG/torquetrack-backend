from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.permissions import HasRolePermission, has_role_permission
from apps.quotes.models import Quote
from apps.quotes.services import (
    TAX_OVERRIDE_PERMISSION,
    convert_quote_to_order,
    delete_or_archive_quote,
    ensure_public_token,
    estimate_admin_quote_tax,
    list_admin_quotes,
    reopen_quote,
    send_quote_email,
    upsert_admin_quote,
)
from apps.vin.services import decode_vehicle
from config.responses import service_response


class _AdminQuoteActionView(APIView):
    permission_classes = [HasRolePermission]

    def _get_quote(self, quote_id):
        return Quote.objects.filter(pk=quote_id).first()


class QuoteConvertView(_AdminQuoteActionView):
    required_permission = "quotes.convert"

    def post(self, request, quote_id):
        quote = self._get_quote(quote_id)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)

        result = convert_quote_to_order(quote, request.user.email)
        return service_response(result)


class QuotePreviewView(_AdminQuoteActionView):
    """Pese al nombre de la ruta no renderiza nada: devuelve la URL del enlace
    público y crea su token si faltaba."""

    required_permission = "quotes.view"

    def post(self, request, quote_id):
        quote = self._get_quote(quote_id)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)

        url = ensure_public_token(quote)
        return Response({"ok": True, "url": url})


class QuoteReopenView(_AdminQuoteActionView):
    required_permission = "quotes.edit"

    def post(self, request, quote_id):
        quote = self._get_quote(quote_id)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)

        reopen_quote(quote)
        return Response({"ok": True})


class QuoteSendView(_AdminQuoteActionView):
    required_permission = "quotes.send"

    def post(self, request, quote_id):
        quote = self._get_quote(quote_id)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)

        result = send_quote_email(quote, request.user.email)
        return service_response(result)


class AdminQuoteVinView(APIView):
    """El editor de cotizaciones decodifica el VIN sin salir de `/api/admin/`."""

    permission_classes = [HasRolePermission]
    required_permission = "quotes.create"

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return service_response(decode_vehicle(body.get("vin")))


class AdminQuoteTaxView(APIView):
    """El impuesto lo calcula el mismo servicio que el checkout, con la
    exención del cliente de la cotización y nunca la del empleado."""

    permission_classes = [HasRolePermission]
    required_permission = "quotes.create"

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        return Response(estimate_admin_quote_tax(body))


class AdminQuoteListCreateView(APIView):
    """El listado y el alta comparten URL, así que el permiso depende del
    método: `required_permission` es una property porque
    `HasRolePermission` la lee en `initial()`, cuando `self.request` ya
    existe."""

    permission_classes = [HasRolePermission]

    @property
    def required_permission(self):
        return "quotes.create" if self.request.method == "POST" else "quotes.view"

    def get(self, request):
        return Response(list_admin_quotes())

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        # Con `id` el POST edita una cotización existente, así que además del
        # alta exige el permiso de edición.
        if body.get("id") and not has_role_permission(request.user, "quotes.edit"):
            return Response({"error": "Forbidden"}, status=403)
        # El servicio decide si el override vale; la view solo resuelve el
        # permiso, como `audit` con `payments.transaction_id`.
        result = upsert_admin_quote(
            body,
            request.user.email,
            can_override_tax=has_role_permission(request.user, TAX_OVERRIDE_PERMISSION),
        )
        return service_response(result)


class QuoteDeleteView(_AdminQuoteActionView):
    required_permission = "quotes.delete"

    def delete(self, request, quote_id):
        quote = self._get_quote(quote_id)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)

        result = delete_or_archive_quote(quote, request.user.email)
        return Response(result)
