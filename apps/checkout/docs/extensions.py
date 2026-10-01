"""Extensiones de drf-spectacular de `apps.checkout`: reemplazan la view por
una subclase con `@extend_schema` solo al generar el esquema."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema

from apps.authorization.docs.schemas import ErrorResponseSerializer
from apps.checkout.docs import examples as ex
from apps.checkout.docs.schemas import (
    CheckoutRequestSerializer,
    CheckoutResponseSerializer,
    FulfillmentRequestSerializer,
    FulfillmentSerializer,
    OrderPatchSerializer,
    OrderSummarySerializer,
    PaymentLinkSerializer,
    RefundRequestSerializer,
    RefundSerializer,
    WebhookAckSerializer,
)

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
                        ErrorResponseSerializer,
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


class AdminOrderFulfillmentViewExtension(OpenApiViewExtension):
    target_class = "apps.checkout.views.admin.AdminOrderFulfillmentView"

    def view_replacement(self):
        class AdminOrderFulfillmentView(self.target_class):
            @extend_schema(
                operation_id="admin_order_fulfillment_update",
                tags=[ADMIN_ORDERS_TAG],
                summary="Update an order's fulfillment",
                description=(
                    "Requires `orders.status`. Moves the shipment of a paid order forward; "
                    "`status` (the order status) is not changed.\n\n"
                    "- Only orders whose `paymentStatus` is `PAID` or `PARTIALLY_REFUNDED` "
                    "and that are not `CANCELLED` or `REJECTED`.\n"
                    "- Forward only: `UNFULFILLED -> PREPARING -> SHIPPED -> DELIVERED`, and "
                    "`UNFULFILLED -> SHIPPED` is allowed.\n"
                    "- `SHIPPED` requires `carrier` and `trackingNumber` and sets `shippedAt`. "
                    "Sending `SHIPPED` again with a different carrier or tracking number "
                    "corrects it and keeps `shippedAt`.\n"
                    "- `DELIVERED` requires the order to be `SHIPPED` and sets `deliveredAt`.\n"
                    "- Shipping (and each correction) emails the customer 'Your TorqueTrack "
                    "order <number> has shipped' with the carrier tracking link, sent in the "
                    "background.\n"
                    "- Logs `FULFILLMENT_UPDATED` in the activity log."
                ),
                parameters=[
                    OpenApiParameter(
                        "order_id", str, OpenApiParameter.PATH, description="Order id."
                    )
                ],
                request=FulfillmentRequestSerializer,
                examples=[ex.FULFILLMENT_SHIP_REQUEST, ex.FULFILLMENT_PREPARING_REQUEST],
                responses={
                    200: OpenApiResponse(
                        FulfillmentSerializer, examples=[ex.FULFILLMENT_SHIPPED]
                    ),
                    400: OpenApiResponse(
                        ErrorResponseSerializer,
                        examples=[
                            ex.INVALID_FULFILLMENT_STATUS,
                            ex.INVALID_CARRIER,
                            ex.TRACKING_REQUIRED,
                            ex.INVALID_TRACKING,
                            ex.SHIPMENT_FIELDS_NOT_ALLOWED,
                        ],
                    ),
                    403: OpenApiResponse(
                        ErrorResponseSerializer,
                        description="No staff session, missing `orders.status`, or CSRF.",
                    ),
                    404: OpenApiResponse(ErrorResponseSerializer, examples=[ex.ORDER_NOT_FOUND]),
                    409: OpenApiResponse(
                        ErrorResponseSerializer,
                        examples=[
                            ex.FULFILLMENT_NOT_PAID,
                            ex.FULFILLMENT_CLOSED,
                            ex.FULFILLMENT_BACKWARDS,
                            ex.FULFILLMENT_ALREADY,
                            ex.FULFILLMENT_SAME_TRACKING,
                        ],
                    ),
                },
            )
            def post(self, request, order_id):
                return super().post(request, order_id)

        return AdminOrderFulfillmentView


class AdminOrdersListViewExtension(OpenApiViewExtension):
    target_class = "apps.checkout.views.admin.AdminOrdersListView"

    def view_replacement(self):
        class AdminOrdersListView(self.target_class):
            @extend_schema(
                operation_id="admin_orders_list",
                tags=[ADMIN_ORDERS_TAG],
                summary="List orders",
                description=(
                    "Requires `orders.view`. Stripe ids appear only with "
                    "`payments.transaction_id`."
                ),
                responses={
                    200: OpenApiResponse(OrderSummarySerializer(many=True)),
                    401: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def get(self, request):
                return super().get(request)

        return AdminOrdersListView


class AdminOrderDetailViewExtension(OpenApiViewExtension):
    target_class = "apps.checkout.views.admin.AdminOrderDetailView"

    def view_replacement(self):
        class AdminOrderDetailView(self.target_class):
            @extend_schema(
                operation_id="admin_order_update",
                tags=[ADMIN_ORDERS_TAG],
                summary="Update an order",
                description=(
                    "Staff session required. `status` needs `orders.status`, except "
                    "`CANCELLED`, which needs `orders.cancel`. An illegal status jump is 409."
                ),
                parameters=[OpenApiParameter("order_id", str, OpenApiParameter.PATH)],
                request=OrderPatchSerializer,
                responses={
                    200: OpenApiResponse(OrderSummarySerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    401: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                    409: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def patch(self, request, order_id):
                return super().patch(request, order_id)

            @extend_schema(
                operation_id="admin_order_delete",
                tags=[ADMIN_ORDERS_TAG],
                summary="Delete an order",
                description="Requires `orders.cancel`.",
                parameters=[OpenApiParameter("order_id", str, OpenApiParameter.PATH)],
                responses={
                    200: OpenApiResponse(OrderSummarySerializer),
                    401: OpenApiResponse(ErrorResponseSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def delete(self, request, order_id):
                return super().delete(request, order_id)

        return AdminOrderDetailView


class AdminOrderPaymentLinkViewExtension(OpenApiViewExtension):
    target_class = "apps.checkout.views.admin.AdminOrderPaymentLinkView"

    def view_replacement(self):
        class AdminOrderPaymentLinkView(self.target_class):
            @extend_schema(
                operation_id="admin_order_payment_link",
                tags=[ADMIN_ORDERS_TAG],
                summary="Email a payment link",
                description="Requires `payments.take`.",
                parameters=[OpenApiParameter("order_id", str, OpenApiParameter.PATH)],
                request=None,
                responses={
                    200: OpenApiResponse(PaymentLinkSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                    409: OpenApiResponse(ErrorResponseSerializer),
                    503: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def post(self, request, order_id):
                return super().post(request, order_id)

        return AdminOrderPaymentLinkView


class AdminOrderTakePaymentViewExtension(OpenApiViewExtension):
    target_class = "apps.checkout.views.admin.AdminOrderTakePaymentView"

    def view_replacement(self):
        class AdminOrderTakePaymentView(self.target_class):
            @extend_schema(
                operation_id="admin_order_take_payment",
                tags=[ADMIN_ORDERS_TAG],
                summary="Take payment",
                description="Requires `payments.take`.",
                parameters=[OpenApiParameter("order_id", str, OpenApiParameter.PATH)],
                request=None,
                responses={
                    200: OpenApiResponse(PaymentLinkSerializer),
                    403: OpenApiResponse(ErrorResponseSerializer),
                    404: OpenApiResponse(ErrorResponseSerializer),
                    409: OpenApiResponse(ErrorResponseSerializer),
                    503: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def post(self, request, order_id):
                return super().post(request, order_id)

        return AdminOrderTakePaymentView


class CheckoutViewExtension(OpenApiViewExtension):
    target_class = "apps.checkout.views.storefront.CheckoutView"

    def view_replacement(self):
        class CheckoutView(self.target_class):
            @extend_schema(
                operation_id="checkout_start",
                tags=["storefront"],
                summary="Start checkout",
                description=(
                    "Public. Creates a pending order and a Stripe Checkout session. "
                    "`vehicle` is optional; when it carries a `vin`, the VIN must have "
                    "17 valid characters and the cart must pass the fitment check.\n\n"
                    "`customer.state` is required and must be the 2-letter code of a US "
                    "state, DC or inhabited territory; `customer.zip` is required (5 digits "
                    "or ZIP+4). Either problem answers 400 and creates no order."
                ),
                auth=[],
                request=CheckoutRequestSerializer,
                responses={
                    200: OpenApiResponse(CheckoutResponseSerializer),
                    400: OpenApiResponse(
                        ErrorResponseSerializer,
                        examples=[
                            ex.SHIPPING_STATE_MISSING,
                            ex.SHIPPING_STATE_INVALID,
                            ex.SHIPPING_ZIP_INVALID,
                            ex.SHIPPING_ZIP_UNKNOWN,
                            ex.SHIPPING_ZIP_MISMATCH,
                        ],
                    ),
                    503: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def post(self, request):
                return super().post(request)

        return CheckoutView


class StripeWebhookViewExtension(OpenApiViewExtension):
    target_class = "apps.checkout.views.webhooks.StripeWebhookView"

    def view_replacement(self):
        class StripeWebhookView(self.target_class):
            @extend_schema(
                operation_id="stripe_webhook",
                tags=["webhooks"],
                summary="Stripe webhook",
                description="Stripe signature required. Not a browser route.",
                auth=[],
                request=None,
                responses={
                    200: OpenApiResponse(WebhookAckSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    503: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def post(self, request):
                return super().post(request)

        return StripeWebhookView
