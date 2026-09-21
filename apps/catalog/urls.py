from rest_framework.routers import SimpleRouter

from apps.catalog.views import ApplicationPublicViewSet, ProductPublicViewSet

router = SimpleRouter(trailing_slash=True)
router.register("products", ProductPublicViewSet, basename="product")
router.register("applications", ApplicationPublicViewSet, basename="application")

urlpatterns = router.urls
