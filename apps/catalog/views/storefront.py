from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.catalog.models import Application, Product
from apps.catalog.serializers import ApplicationPublicSerializer, ProductPublicSerializer


class ProductPublicViewSet(ReadOnlyModelViewSet):
    queryset = Product.objects.filter(active=True).order_by("id")
    serializer_class = ProductPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class ApplicationPublicViewSet(ReadOnlyModelViewSet):
    queryset = Application.objects.order_by("id")
    serializer_class = ApplicationPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = None
