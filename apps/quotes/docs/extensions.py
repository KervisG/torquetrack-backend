"""Extensiones de drf-spectacular de `apps.quotes`."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)

from apps.authorization.docs.schemas import ErrorResponseSerializer, OkResponseSerializer
from apps.quotes.docs.schemas import (
    CheckoutLinkSerializer,
    QuoteRequestSerializer,
    QuoteSerializer,
    QuoteTaxRequestSerializer,
    QuoteWriteSerializer,
    VinRequestSerializer,
)

ERR = OpenApiResponse(ErrorResponseSerializer)
QUOTE_ID = OpenApiParameter("quote_id", str, OpenApiParameter.PATH)
TOKEN = OpenApiParameter("token", str, OpenApiParameter.PATH)
ADMIN = "admin: quotes"


def _action(operation_id, summary, description):
    return extend_schema(
        operation_id=operation_id,
        tags=[ADMIN],
        summary=summary,
        description=description,
        parameters=[QUOTE_ID],
        request=None,
        responses={200: OpenApiResponse(QuoteSerializer), 403: ERR, 404: ERR, 409: ERR},
    )


class QuoteRequestViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.storefront.QuoteRequestView"

    def view_replacement(self):
        class QuoteRequestView(self.target_class):
            @extend_schema(
                operation_id="quote_request",
                tags=["storefront"],
                summary="Request a quote",
                auth=[],
                request=QuoteRequestSerializer,
                responses={201: OpenApiResponse(OkResponseSerializer), 400: ERR},
            )
            def post(self, request):
                return super().post(request)

        return QuoteRequestView


class PublicQuoteViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.storefront.PublicQuoteView"

    def view_replacement(self):
        class PublicQuoteView(self.target_class):
            @extend_schema(
                operation_id="quote_public",
                tags=["storefront"],
                summary="Read a public quote",
                auth=[],
                parameters=[TOKEN],
                responses={200: OpenApiResponse(QuoteSerializer), 404: ERR},
            )
            def get(self, request, token):
                return super().get(request, token)

        return PublicQuoteView


class PublicQuoteDetailsViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.storefront.PublicQuoteDetailsView"

    def view_replacement(self):
        class PublicQuoteDetailsView(self.target_class):
            @extend_schema(
                operation_id="quote_public_details",
                tags=["storefront"],
                summary="Save public quote details",
                auth=[],
                parameters=[TOKEN],
                responses={200: OpenApiResponse(QuoteSerializer), 404: ERR, 410: ERR},
            )
            def get(self, request, token):
                return super().get(request, token)

        return PublicQuoteDetailsView


class PublicQuoteCheckoutViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.storefront.PublicQuoteCheckoutView"

    def view_replacement(self):
        class PublicQuoteCheckoutView(self.target_class):
            @extend_schema(
                operation_id="quote_public_checkout",
                tags=["storefront"],
                summary="Start checkout from a public quote",
                auth=[],
                parameters=[TOKEN],
                request=None,
                responses={
                    200: OpenApiResponse(CheckoutLinkSerializer),
                    400: ERR,
                    404: ERR,
                    503: ERR,
                },
            )
            def post(self, request, token):
                return super().post(request, token)

        return PublicQuoteCheckoutView


class PublicQuotePdfViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.pdf.PublicQuotePdfView"

    def view_replacement(self):
        class PublicQuotePdfView(self.target_class):
            @extend_schema(
                operation_id="quote_public_pdf",
                tags=["storefront"],
                summary="Download a public quote PDF",
                auth=[],
                parameters=[TOKEN],
                responses={
                    (200, "application/pdf"): OpenApiResponse(OpenApiTypes.BINARY),
                    404: ERR,
                },
            )
            def get(self, request, token):
                return super().get(request, token)

        return PublicQuotePdfView


class AdminQuoteListCreateViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.admin.AdminQuoteListCreateView"

    def view_replacement(self):
        @extend_schema_view(
            get=extend_schema(
                operation_id="admin_quotes_list",
                tags=[ADMIN],
                summary="List quotes",
                description="Requires `quotes.view`.",
                responses={200: OpenApiResponse(QuoteSerializer(many=True)), 403: ERR},
            ),
            post=extend_schema(
                operation_id="admin_quotes_create",
                tags=[ADMIN],
                summary="Create a quote",
                description="Requires `quotes.edit`.",
                request=QuoteWriteSerializer,
                responses={201: OpenApiResponse(QuoteSerializer), 400: ERR, 403: ERR},
            ),
        )
        class AdminQuoteListCreateView(self.target_class):
            pass

        return AdminQuoteListCreateView


class QuoteDeleteViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.admin.QuoteDeleteView"

    def view_replacement(self):
        class QuoteDeleteView(self.target_class):
            @_action("admin_quote_delete", "Delete a quote", "Requires `quotes.delete`.")
            def delete(self, request, quote_id):
                return super().delete(request, quote_id)

        return QuoteDeleteView


class QuoteConvertViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.admin.QuoteConvertView"

    def view_replacement(self):
        class QuoteConvertView(self.target_class):
            @_action(
                "admin_quote_convert",
                "Convert a quote to an order",
                "Requires `quotes.convert`.",
            )
            def post(self, request, quote_id):
                return super().post(request, quote_id)

        return QuoteConvertView


class QuotePreviewViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.admin.QuotePreviewView"

    def view_replacement(self):
        class QuotePreviewView(self.target_class):
            @_action("admin_quote_preview", "Preview a quote", "Requires `quotes.view`.")
            def post(self, request, quote_id):
                return super().post(request, quote_id)

        return QuotePreviewView


class QuoteReopenViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.admin.QuoteReopenView"

    def view_replacement(self):
        class QuoteReopenView(self.target_class):
            @_action("admin_quote_reopen", "Reopen a quote", "Requires `quotes.edit`.")
            def post(self, request, quote_id):
                return super().post(request, quote_id)

        return QuoteReopenView


class QuoteSendViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.admin.QuoteSendView"

    def view_replacement(self):
        class QuoteSendView(self.target_class):
            @_action("admin_quote_send", "Email a quote", "Requires `quotes.send`.")
            def post(self, request, quote_id):
                return super().post(request, quote_id)

        return QuoteSendView


class AdminQuoteVinViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.admin.AdminQuoteVinView"

    def view_replacement(self):
        class AdminQuoteVinView(self.target_class):
            @extend_schema(
                operation_id="admin_quote_vin",
                tags=[ADMIN],
                summary="Decode a VIN for a quote",
                description="Requires `quotes.edit`.",
                request=VinRequestSerializer,
                responses={200: OpenApiResponse(QuoteSerializer), 400: ERR, 403: ERR, 502: ERR},
            )
            def post(self, request):
                return super().post(request)

        return AdminQuoteVinView


class AdminQuoteTaxViewExtension(OpenApiViewExtension):
    target_class = "apps.quotes.views.admin.AdminQuoteTaxView"

    def view_replacement(self):
        class AdminQuoteTaxView(self.target_class):
            @extend_schema(
                operation_id="admin_quote_tax",
                tags=[ADMIN],
                summary="Estimate tax for a quote",
                description="Requires `quotes.edit`.",
                request=QuoteTaxRequestSerializer,
                responses={200: OpenApiResponse(QuoteSerializer), 400: ERR, 403: ERR},
            )
            def post(self, request):
                return super().post(request)

        return AdminQuoteTaxView
