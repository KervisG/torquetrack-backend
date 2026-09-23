"""Vistas de `POST /api/quote/request`, `GET /api/quote/public/<token>`
(HTML heredado), `GET /api/quote/public/<token>/details/` (JSON de la página
`/quote/<token>` del SPA, que es lo que enlaza el correo) y
`POST /api/quote/public/<token>/checkout`.

Las dos rutas públicas por token son `AllowAny` a propósito: el control de
acceso es poseer un token imposible de adivinar, no una sesión. Lo fija
`apps/quotes/tests/test_public_views.py`.
"""
from django.http import HttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auth.authentication import SessionUserAuthentication
from apps.quotes.models import Quote
from apps.quotes.services import (
    checkout_from_quote,
    create_quote_from_request,
    is_expired,
    render_quote_html,
    serialize_public_quote,
    serialize_quote,
)


def _find_by_token(token: str) -> Quote | None:
    return Quote.objects.filter(data__publicToken=token).select_related("customer").first()


class QuoteRequestView(APIView):
    """Sesión opcional: con ella la cotización queda en el `Customer` de la
    cuenta y se exige CSRF; sin ella es una solicitud invitada."""

    authentication_classes = [SessionUserAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        result = create_quote_from_request(body, request.user)
        status = result.pop("status", 200) if "error" in result else 200
        return Response(result, status=status)


class PublicQuoteView(APIView):
    """`GET /api/quote/public/<token>`: devuelve directamente la página HTML
    interactiva de la cotización (`text/html`, no JSON)."""

    permission_classes = [AllowAny]

    def get(self, request, token):
        quote = _find_by_token(token)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)
        if is_expired(quote):
            # Un token vencido se rechaza en todas las rutas públicas, no solo
            # en el checkout (ver test_public_views.py). El chequeo de
            # vencimiento es de solo lectura y nunca cambia `status`, así que
            # la cotización no se reabre sola.
            return Response({"error": "This quote has expired"}, status=410)

        print_mode = request.GET.get("print") == "1"
        public_url = f"{request.build_absolute_uri('/api/quote/public/')}{token}"
        quote_dict = serialize_quote(quote)
        html = render_quote_html(quote_dict, public_url=public_url, print_mode=print_mode)
        response = HttpResponse(html, content_type="text/html; charset=utf-8")
        response["Cache-Control"] = "no-store"
        return response


class PublicQuoteDetailsView(APIView):
    """`GET /api/quote/public/<token>/details/`: misma regla de acceso y de
    vencimiento que la página HTML, en JSON y solo con los datos del cliente."""

    permission_classes = [AllowAny]

    def get(self, request, token):
        quote = _find_by_token(token)
        if quote is None:
            return Response({"error": "Quote not found"}, status=404)
        if is_expired(quote):
            return Response({"error": "This quote has expired"}, status=410)

        response = Response(serialize_public_quote(quote))
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
