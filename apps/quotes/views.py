"""`POST /api/quote/request`, `GET /api/quote/public/<token>`, and
`POST /api/quote/public/<token>/checkout` (task 6.1), matching
`app/api/quote/request/route.ts` and `app/api/quote/public/[token]/**`.

Both public token routes are `AllowAny` by design — access control is
possession of an unguessable token, not a session (spec: "Public
Magic-Link Quote Access") — asserted by
`apps/quotes/tests/test_public_views.py`.
"""
from django.http import HttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.quotes.models import Quote
from apps.quotes.services import (
    checkout_from_quote,
    create_quote_from_request,
    is_expired,
    render_quote_html,
    serialize_quote,
)


def _find_by_token(token: str) -> Quote | None:
    return Quote.objects.filter(data__publicToken=token).select_related("customer").first()


class QuoteRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        result = create_quote_from_request(body)
        status = result.pop("status", 200) if "error" in result else 200
        return Response(result, status=status)


class PublicQuoteView(APIView):
    """`GET /api/quote/public/<token>` — renders the interactive quote
    HTML page directly (not JSON), matching the legacy route's
    `text/html` response."""

    permission_classes = [AllowAny]

    def get(self, request, token):
        quote = _find_by_token(token)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)
        if is_expired(quote):
            # Deviation from the legacy route (documented in
            # test_public_views.py): the spec explicitly requires expired
            # tokens to be denied everywhere, not just at checkout. A
            # read-only expiry check never mutates `status`, so "no
            # auto-reopen" holds.
            return Response({"error": "This quote has expired"}, status=410)

        print_mode = request.GET.get("print") == "1"
        public_url = f"{request.build_absolute_uri('/api/quote/public/')}{token}"
        quote_dict = serialize_quote(quote)
        html = render_quote_html(quote_dict, public_url=public_url, print_mode=print_mode)
        response = HttpResponse(html, content_type="text/html; charset=utf-8")
        response["Cache-Control"] = "no-store"
        return response


class PublicQuoteCheckoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, token):
        quote = _find_by_token(token)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)

        result = checkout_from_quote(quote)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status"])
        return Response(result)
