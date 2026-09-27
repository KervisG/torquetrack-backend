"""Extensiones de drf-spectacular de `apps.cart`: reemplazan la view por una
subclase con `@extend_schema` solo al generar el esquema."""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiResponse, extend_schema

from apps.authorization.docs import examples as shared_ex
from apps.authorization.docs.schemas import ErrorResponseSerializer
from apps.cart.docs import examples as ex
from apps.cart.docs.schemas import AdminCartSerializer, CartRequestSerializer, CartSerializer

CART_TAG = "cart"


class CartViewExtension(OpenApiViewExtension):
    target_class = "apps.cart.views.storefront.CartView"

    def view_replacement(self):
        class CartView(self.target_class):
            @extend_schema(
                operation_id="cart_read",
                tags=[CART_TAG],
                summary="Read the cart",
                description=(
                    "Public, optional session. With a signed-in session it is the "
                    "account cart, the same on every device; otherwise it is the "
                    "guest cart of the session. Every line is repriced from the "
                    "catalog; products that are no longer active are left out. Each "
                    "line keeps the catalog price from when it was added "
                    "(`priceAtAdd`, set by the server); when the current price "
                    "differs the line has `priceChanged: true` and `previousPrice`, "
                    "and `notices` explains the change. The total always uses the "
                    "current price. A cart saved before this reference existed takes "
                    "the current price as its reference on the first read, without "
                    "a notice."
                ),
                responses={
                    200: OpenApiResponse(
                        CartSerializer,
                        examples=[ex.CART, ex.PRICE_CHANGED_CART, ex.EMPTY_CART],
                    )
                },
            )
            def get(self, request):
                return super().get(request)

            @extend_schema(
                operation_id="cart_replace",
                tags=[CART_TAG],
                summary="Replace the cart items",
                description=(
                    "Public, optional session; a signed-in session must send "
                    "`X-CSRFToken`. Replaces every line with `items` (`id` of an "
                    "active product, whole `qty` from 1 to 99, each product once, "
                    "at most 100 lines) and answers the repriced cart. Any price in "
                    "the body is ignored, and so is a `cartId`. An empty `items` "
                    "deletes the cart. Signing in merges the guest cart into the "
                    "account cart: quantities of the same product are added, "
                    "capped at 99. Price notices: a new product takes the current "
                    "catalog price as its reference (`priceAtAdd` in the body is "
                    "ignored); a product already in the cart keeps its reference, "
                    "so the notice stays, unless the body has `acknowledgePrices: "
                    "true`, which moves every reference to the current price. On "
                    "sign-in the account cart reference wins, then the guest one."
                ),
                request=CartRequestSerializer,
                examples=[ex.CART_REQUEST, ex.ACKNOWLEDGE_REQUEST],
                responses={
                    200: OpenApiResponse(
                        CartSerializer,
                        examples=[ex.CART, ex.PRICE_CHANGED_CART, ex.EMPTY_CART],
                    ),
                    400: OpenApiResponse(
                        ErrorResponseSerializer,
                        examples=[
                            ex.MALFORMED_ITEMS,
                            ex.INVALID_QUANTITY,
                            ex.DUPLICATE_ITEM,
                            ex.TOO_MANY_LINES,
                            ex.UNAVAILABLE_PRODUCT,
                            shared_ex.MALFORMED_JSON,
                        ],
                    ),
                    403: OpenApiResponse(
                        ErrorResponseSerializer,
                        description="Signed-in session without a valid CSRF token.",
                        examples=[shared_ex.CSRF_FAILED],
                    ),
                    415: OpenApiResponse(
                        ErrorResponseSerializer, examples=[shared_ex.UNSUPPORTED_MEDIA_TYPE]
                    ),
                },
            )
            def put(self, request):
                return super().put(request)

        return CartView


class AdminCartsViewExtension(OpenApiViewExtension):
    target_class = "apps.cart.views.admin.AdminCartsView"

    def view_replacement(self):
        class AdminCartsView(self.target_class):
            @extend_schema(
                operation_id="admin_carts_list",
                tags=["admin: carts"],
                summary="List carts",
                description=(
                    "Requires `carts.view`. Read only: carts without items are left "
                    "out and removed with `manage.py purge_carts`. A `CART` stage "
                    "shows `ACTIVE`, or `ABANDONED` after 30 idle minutes; other "
                    "stages show as they are. Account carts include `email`."
                ),
                responses={
                    200: AdminCartSerializer(many=True),
                    403: OpenApiResponse(
                        ErrorResponseSerializer,
                        description="No staff session or missing `carts.view`.",
                    ),
                },
            )
            def get(self, request):
                return super().get(request)

        return AdminCartsView
