"""Extensiones de drf-spectacular de `apps.checkout`: reemplazan la view por
una subclase con `@extend_schema` solo al generar el esquema."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema

from apps.authorization.docs.schemas import ErrorOrDetailResponse, ErrorResponseSerializer
from apps.checkout.docs import examples as ex
from apps.checkout.docs.schemas import RefundRequestSerializer, RefundSerializer

ADMIN_ORDERS_TAG = "admin: orders"


class AdminOrderRefundsViewExtension(OpenApiViewExtension):
    target_class = "apps.checkout.views.admin.AdminOrderRefundsView"

    def view_replacement(self):
        class AdminOrderRefundsView(self.target_class):
            @extend_schema(
                operation_id="admin_order_refund_create",
                tags=[ADMIN_ORDERS_TAG],
                summary="Refund an order",
                description=(
                    "Requires `payments.refund`. Refunds the Stripe charge that paid the "
                    "order, only while `paymentStatus` is `PAID` or `PARTIALLY_REFUNDED`.\n\n"
                    "- Without `amount` it refunds the remaining balance: the charged "
                    "amount minus `PENDING` and `SUCCEEDED` refunds.\n"
                    "- The refund row is saved before calling Stripe and its id is the "
                    "Stripe idempotency key.\n"
                    "- A succeeded refund moves the order to `PARTIALLY_REFUNDED` or "
                    "`REFUNDED`; `status` is not changed.\n"
                    "- Logs `REFUND_CREATED` or `REFUND_FAILED` in the activity log.\n"
                    "- `stripeRefundId` is returned only with `payments.transaction_id`."
                ),
                parameters=[
                    OpenApiParameter(
                        "order_id", str, OpenApiParameter.PATH, description="Order id."
                    )
                ],
                request=RefundRequestSerializer,
                examples=[ex.REFUND_REQUEST],
                responses={
                    201: OpenApiResponse(RefundSerializer, examples=[ex.REFUND_CREATED]),
                    400: OpenApiResponse(
                        ErrorResponseSerializer,
                        examples=[
                            ex.INVALID_AMOUNT,
                            ex.AMOUNT_OVER_BALANCE,
                            ex.REASON_NOT_TEXT,
                            ex.REASON_TOO_LONG,
                        ],
                    ),
                    403: OpenApiResponse(
                        ErrorOrDetailResponse,
                        description="No staff session, missing `payments.refund`, or CSRF.",
                    ),
                    404: OpenApiResponse(ErrorResponseSerializer, examples=[ex.ORDER_NOT_FOUND]),
                    409: OpenApiResponse(
                        ErrorResponseSerializer,
                        examples=[ex.NOT_PAID, ex.NO_STRIPE_CHARGE, ex.NO_BALANCE],
                    ),
                    502: OpenApiResponse(
                        ErrorResponseSerializer,
                        description="Stripe rejected or did not answer; details are in the logs.",
                        examples=[ex.STRIPE_FAILED],
                    ),
                },
            )
            def post(self, request, order_id):
                return super().post(request, order_id)

        return AdminOrderRefundsView
