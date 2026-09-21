"""`POST /api/fitment/check`, matching `app/api/fitment/check/route.ts`."""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.fitment.services import check_product_fitment


def _item_id(item) -> str:
    if isinstance(item, dict):
        return str(item.get("id") or item.get("productId") or "")
    return ""


class FitmentCheckView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        vehicle = request.data.get("vehicle")
        if vehicle is None:
            return Response({"error": "Vehicle required"}, status=400)

        items = request.data.get("items")
        items = items if isinstance(items, list) else []
        # Legacy quirk preserved: the length check is on the mapped id
        # list, which is always the same length as `items` itself — an
        # item with no id/productId still counts toward "not empty".
        ids = [_item_id(item) for item in items]
        if not ids:
            return Response({"error": "Cart is empty"}, status=400)

        products = Product.objects.filter(id__in=ids, active=True)
        results = []
        for product in products:
            data = product.data or {}
            fitment = check_product_fitment(data, vehicle)
            results.append(
                {
                    "id": product.id,
                    "title": data.get("title"),
                    "partNumber": data.get("partNumber")
                    or data.get("oemPart")
                    or data.get("aftermarketPart")
                    or "",
                    **fitment,
                }
            )

        compatible = all(result["compatible"] for result in results)
        return Response({"compatible": compatible, "results": results})
