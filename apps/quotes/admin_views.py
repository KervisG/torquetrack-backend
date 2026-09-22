"""Admin quote actions (task 6.3): convert/preview/reopen/send, plus
list/create/delete (task 7.6, closing the scope gap flagged by Phase 6),
matching `app/api/admin/quotes/[id]/{convert,preview,reopen,send}/route.ts`,
`app/api/admin/quotes/route.ts`, and `app/api/admin/quotes/[id]/route.ts`.

RBAC-gated via `HasTorqueTrackPermission` + `AdminSessionAuthentication`
(Phase 6 prerequisite, see `apps/auth/authentication.py`).
"""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.permissions import HasTorqueTrackPermission
from apps.auth.authentication import AdminSessionAuthentication
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
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [HasTorqueTrackPermission]

    def _get_quote(self, quote_id):
        return Quote.objects.filter(pk=quote_id).first()


class QuoteConvertView(_AdminQuoteActionView):
    required_permission = "quotes.convert"

    def post(self, request, quote_id):
        quote = self._get_quote(quote_id)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)

        result = convert_quote_to_order(quote, request.user.username)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class QuotePreviewView(_AdminQuoteActionView):
    """Despite the legacy route's name, this generates/reuses the public
    magic-link token and returns its URL — it does not render a preview
    body (see `app/api/admin/quotes/[id]/preview/route.ts`)."""

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

        result = send_quote_email(quote, request.user.username)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class AdminQuoteListCreateView(APIView):
    """`GET/POST /api/admin/quotes` (task 7.6): list (`quotes.view`) and
    create/update (`quotes.create`) share one URL, so the required
    permission depends on the request method — `HasTorqueTrackPermission`
    reads `required_permission` before the handler runs, hence the
    property (evaluated once `self.request` exists in `initial()`)."""

    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [HasTorqueTrackPermission]

    @property
    def required_permission(self):
        return "quotes.create" if self.request.method == "POST" else "quotes.view"

    def get(self, request):
        return Response(list_admin_quotes())

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        result = upsert_admin_quote(body, request.user.username)
        if "error" in result:
            return Response({"error": result["error"]}, status=result.get("status", 400))
        return Response(result)


class QuoteDeleteView(_AdminQuoteActionView):
    required_permission = "quotes.delete"

    def delete(self, request, quote_id):
        quote = self._get_quote(quote_id)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)

        result = delete_or_archive_quote(quote, request.user.username)
        return Response(result)
