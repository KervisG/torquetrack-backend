"""Vistas públicas de lectura del catálogo.

`retrieve` (detalle) sale de la convención `ReadOnlyModelViewSet` de DRF y
aplica las mismas reglas de lista blanca que `list`.
"""
from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.catalog.models import Application, Product
from apps.catalog.serializers import ApplicationPublicSerializer, ProductPublicSerializer


class ProductPublicViewSet(ReadOnlyModelViewSet):
    """`GET /api/products/`, `GET /api/products/<id>/`.

    Solo filas `active=true`, ordenadas por `id`, sin los campos internos de
    costo y proveedor.
    """

    queryset = Product.objects.filter(active=True).order_by("id")
    serializer_class = ProductPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class ApplicationPublicViewSet(ReadOnlyModelViewSet):
    """`GET /api/applications/`, `GET /api/applications/<id>/`.

    Todas las filas, ordenadas por `id`, sin quitar ningún campo.
    """

    queryset = Application.objects.order_by("id")
    serializer_class = ApplicationPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = None
