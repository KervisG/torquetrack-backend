"""Public read views for the catalog app (task 4.1).

`retrieve` (detail) has no legacy Next.js equivalent — the frozen app has
no `products/[id]`/`applications/[id]` route. Adding it here is a
DRF-native addition per the design's `ModelViewSet` convention; it is not a
contract this phase needs to match against a legacy response, only against
the same whitelist rules as `list`.
"""
from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.catalog.models import Application, Product
from apps.catalog.serializers import ApplicationPublicSerializer, ProductPublicSerializer


class ProductPublicViewSet(ReadOnlyModelViewSet):
    """`GET /api/products/`, `GET /api/products/<id>/`.

    Matches `app/api/products/route.ts`: only `active=true` rows, ordered
    by `id`, internal cost/supplier fields stripped.
    """

    queryset = Product.objects.filter(active=True).order_by("id")
    serializer_class = ProductPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class ApplicationPublicViewSet(ReadOnlyModelViewSet):
    """`GET /api/applications/`, `GET /api/applications/<id>/`.

    Matches `app/api/applications/route.ts`: all rows, ordered by `id`, no
    field stripping.
    """

    queryset = Application.objects.order_by("id")
    serializer_class = ApplicationPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = None
