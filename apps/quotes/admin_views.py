"""Vistas de admin de cotizaciones: acciones convert/preview/reopen/send
(`admin/quotes/[id]/*`) más listado, alta y baja (`admin/quotes` y
`admin/quotes/[id]`).

Protegidas con `HasTorqueTrackPermission` + `SessionUserAuthentication`
(ver `apps/auth/authentication.py`).
"""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.authentication import SessionUserAuthentication
from apps.auth.permissions import HasTorqueTrackPermission
from apps.quotes.admin_services import (
    convert_quote_to_order,
    delete_or_archive_quote,
    ensure_public_token,
    list_admin_quotes,
    reopen_quote,
    send_quote_email,
    upsert_admin_quote,
)
from apps.quotes.models import Quote


class _AdminQuoteActionView(APIView):
    authentication_classes = [SessionUserAuthentication]
    permission_classes = [HasTorqueTrackPermission]

    def _get_quote(self, quote_id):
        return Quote.objects.filter(pk=quote_id).first()


class QuoteConvertView(_AdminQuoteActionView):
    required_permission = "quotes.convert"

    def post(self, request, quote_id):
        quote = self._get_quote(quote_id)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)

        result = convert_quote_to_order(quote, request.user.email)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class QuotePreviewView(_AdminQuoteActionView):
    """Pese al nombre de la ruta, genera o reutiliza el token público del
    magic link y devuelve su URL: no renderiza ningún cuerpo de vista
    previa."""

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
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminQuoteListCreateView(APIView):
    """`GET/POST /api/admin/quotes`: el listado (`quotes.view`) y el alta o
    edición (`quotes.create`) comparten URL, así que el permiso exigido
    depende del método. `HasTorqueTrackPermission` lee `required_permission`
    antes del handler; por eso es una property, evaluada cuando
    `self.request` ya existe en `initial()`."""

    authentication_classes = [SessionUserAuthentication]
    permission_classes = [HasTorqueTrackPermission]

    @property
    def required_permission(self):
        return "quotes.create" if self.request.method == "POST" else "quotes.view"

    def get(self, request):
        return Response(list_admin_quotes())

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        result = upsert_admin_quote(body, request.user.email)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class QuoteDeleteView(_AdminQuoteActionView):
    required_permission = "quotes.delete"

    def delete(self, request, quote_id):
        quote = self._get_quote(quote_id)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)

        result = delete_or_archive_quote(quote, request.user.email)
        return Response(result)
