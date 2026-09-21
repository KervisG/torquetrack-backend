"""`POST /api/checkout` (tasks 5.2, 5.3), matching
`app/api/checkout/route.ts` and `lib/stripe.ts`.
"""
from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cart.models import Cart
from apps.catalog.models import Product
from apps.checkout.models import Order, Payment
from apps.checkout.services import (
    calculate_sales_tax,
    create_stripe_checkout_session,
    js_number_or,
    money,
    next_order_number,
    random_id,
    resolve_or_create_customer,
)
from apps.customers.models import Customer
from apps.fitment.services import check_product_fitment


class CheckoutView(APIView):
    """Server-side repricing from DB state, fitment re-check, customer
    resolve/create, VERIFIED-exemption tax bypass, Order+Payment creation,
    and Stripe Checkout Session creation. Never trusts client-submitted
    prices (spec: "Server-Side Checkout Repricing")."""

    permission_classes = [AllowAny]

    def post(self, request):
        if not settings.STRIPE_SECRET_KEY:
            return Response(
                {
                    "error": "Payments are not configured. Add STRIPE_SECRET_KEY to "
                    "the server environment."
                },
                status=503,
            )

        body = request.data if isinstance(request.data, dict) else {}
        raw_items = body.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            return Response({"error": "Cart is empty"}, status=400)

        ids = [str(raw_item.get("id")) for raw_item in raw_items]
        products_by_id = {
            product.id: (product.data or {})
            for product in Product.objects.filter(id__in=ids, active=True)
        }

        items = []
        pairs = []  # (item, product_data) kept for the fitment re-check below
        subtotal = 0.0
        core_total = 0.0
        for raw_item in raw_items:
            product_data = products_by_id.get(str(raw_item.get("id")))
            if not product_data:
                continue
            qty = max(1, min(99, int(js_number_or(raw_item.get("qty"), 1))))
            price = money(product_data.get("price"))
            core = money(product_data.get("coreCharge"))
            subtotal += price * qty
            core_total += core * qty
            title = (
                product_data.get("title")
                or product_data.get("partNumber")
                or product_data.get("id")
            )
            item = {
                "id": product_data.get("id"),
                "title": title,
                "partNumber": (
                    product_data.get("partNumber")
                    or product_data.get("oemPart")
                    or product_data.get("aftermarketPart")
                    or ""
                ),
                "qty": qty,
                "price": price,
                "coreCharge": core,
            }
            items.append(item)
            pairs.append((item, product_data))

        if not items:
            return Response({"error": "No valid products in cart"}, status=400)

        vehicle = body.get("vehicle") or {}
        incompatible = [
            (item, check_product_fitment(product_data, vehicle)) for item, product_data in pairs
        ]
        incompatible = [(item, check) for item, check in incompatible if not check["compatible"]]
        if incompatible:
            detail = "; ".join(
                f"{item['partNumber'] or item['title']}: {', '.join(check['reasons'])}"
                for item, check in incompatible
            )
            return Response({"error": f"VIN fitment check failed: {detail}"}, status=409)

        shipping_raw = body.get("shipping")
        if isinstance(shipping_raw, dict):
            shipping = money(shipping_raw.get("rate"))
        else:
            shipping = money(shipping_raw)

        customer = body.get("customer") or {}
        customer_id = resolve_or_create_customer(customer) if customer.get("email") else None

        tax_kwargs = {
            "subtotal": subtotal,
            "core_charge": core_total,
            "shipping": shipping,
            "state": customer.get("state"),
            "zip_code": customer.get("zip"),
            "city": customer.get("city"),
            "address1": customer.get("address1"),
        }
        tax_result = {"tax": 0, "rate": 0, "source": "Tax exempt"}
        if customer_id:
            tax_status = (
                Customer.objects.filter(pk=customer_id)
                .values_list("tax_status", flat=True)
                .first()
            )
            if tax_status != "VERIFIED":
                tax_result = calculate_sales_tax(**tax_kwargs)
        else:
            tax_result = calculate_sales_tax(**tax_kwargs)

        tax = money(tax_result["tax"])
        total = money(subtotal + core_total + shipping + tax)
        order_id = random_id("OID")
        number = next_order_number()

        order_data = {
            "customer": customer,
            "vehicle": body.get("vehicle") or {},
            "items": items,
            "shipping": body.get("shipping") or {},
            "cartId": body.get("cartId"),
            "taxSource": tax_result["source"],
            "totals": {
                "subtotal": money(subtotal),
                "core": money(core_total),
                "shipping": shipping,
                "tax": tax,
                "total": total,
            },
        }

        now = timezone.now()
        order = Order.objects.create(
            id=order_id,
            number=number,
            customer_id=customer_id,
            status="PENDING_PAYMENT",
            payment_status="UNPAID",
            data=order_data,
            created_at=now,
            updated_at=now,
        )

        cart_id = body.get("cartId")
        if cart_id:
            cart = Cart.objects.filter(pk=cart_id).first()
            if cart is not None:
                cart.data = {
                    **(cart.data or {}),
                    "stage": "CHECKOUT",
                    "status": "CHECKOUT",
                    "orderId": order_id,
                    "orderNumber": number,
                    "customer": customer,
                }
                cart.updated_at = timezone.now()
                cart.save(update_fields=["data", "updated_at"])

        try:
            session_payload = {"id": order_id, "number": number, **order_data}
            session = create_stripe_checkout_session(session_payload)
        except Exception as exc:  # noqa: BLE001 - mirrors the route's `catch(e:any)`
            order.status = "PAYMENT_SETUP_FAILED"
            order.save(update_fields=["status"])
            return Response({"error": str(exc) or "Could not create secure checkout"}, status=502)

        Payment.objects.create(
            id=random_id("PAY"),
            order=order,
            provider="stripe",
            provider_id=session["id"],
            status="PENDING",
            amount=total,
            data={"sessionId": session["id"]},
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )

        return Response(
            {
                "ok": True,
                "url": session["url"],
                "orderId": order_id,
                "orderNumber": number,
                "tax": tax,
            }
        )
