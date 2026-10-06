from django.http import Http404
from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.catalog.models import Application, Product
from apps.catalog.serializers import ApplicationPublicSerializer, ProductPublicSerializer


class ProductPublicViewSet(ReadOnlyModelViewSet):
    queryset = Product.objects.filter(active=True).prefetch_related("applications").order_by("id")
    serializer_class = ProductPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_object(self):
        """`/api/products/<id o slug>/`. El id gana primero para que las URLs
        viejas por id sigan resolviendo al mismo producto aunque un slug
        coincida con ese id."""
        lookup = self.kwargs[self.lookup_url_kwarg or self.lookup_field]
        queryset = self.get_queryset()
        product = queryset.filter(pk=lookup).first() or queryset.filter(slug=lookup).first()
        if product is None:
            raise Http404
        self.check_object_permissions(self.request, product)
        return product


class ApplicationPublicViewSet(ReadOnlyModelViewSet):
    queryset = Application.objects.order_by("id")
    serializer_class = ApplicationPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = None
