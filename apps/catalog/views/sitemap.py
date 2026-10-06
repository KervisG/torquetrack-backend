from rest_framework.permissions import AllowAny
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.services.sitemap import build_sitemap_xml


class SitemapXmlRenderer(BaseRenderer):
    """Devuelve el XML que ya armó el service, tal cual."""

    media_type = "application/xml"
    format = "xml"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data.encode("utf-8") if isinstance(data, str) else b""


class SitemapView(APIView):
    # Público para los buscadores; sin throttle propio (ver
    # `UNTHROTTLED_PUBLIC_VIEWS`): es una sola lectura del catálogo.
    permission_classes = [AllowAny]
    renderer_classes = [SitemapXmlRenderer]

    def get(self, request):
        return Response(build_sitemap_xml())
