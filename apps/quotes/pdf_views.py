"""`GET /api/quote/public/<token>/pdf` (task 6.2), matching
`app/api/quote/public/[token]/pdf/route.ts`. Separate module from
`views.py` for clean commit splitting (same precedent as Phase 5's
`webhook_views.py`).
"""
from django.http import HttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.quotes.pdf import render_quote_pdf_bytes
from apps.quotes.services import is_expired, serialize_quote
from apps.quotes.views import _find_by_token


class PublicQuotePdfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        quote = _find_by_token(token)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)
        if is_expired(quote):
            # Same deliberate spec-driven deviation as PublicQuoteView.
            return Response({"error": "This quote has expired"}, status=410)

        pdf_bytes = render_quote_pdf_bytes(serialize_quote(quote))
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="TorqueTrack-{quote.number}.pdf"'
        response["Cache-Control"] = "no-store"
        return response
