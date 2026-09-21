"""Admin quote actions (task 6.3): convert/preview/reopen/send, matching
`app/api/admin/quotes/[id]/{convert,preview,reopen,send}/route.ts`.

RBAC-gated via `HasTorqueTrackPermission` + `AdminSessionAuthentication`
(Phase 6 prerequisite, see `apps/accounts/authentication.py`). List/create
(`GET/POST admin/quotes`) and delete (`DELETE admin/quotes/[id]`) are read
for context but are NOT implemented here — they are not named by this
phase's task 6.3 ("admin `quotes` convert/preview/reopen/send routes")
and are not claimed by any other phase's task list either; flagged as a
scope gap in apply-progress rather than silently expanded into here.
"""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import AdminSessionAuthentication
from apps.accounts.permissions import HasTorqueTrackPermission
from apps.quotes.admin_services import (
    convert_quote_to_order,
    ensure_public_token,
    reopen_quote,
    send_quote_email,
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
