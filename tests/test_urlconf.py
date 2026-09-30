"""`config/urls.py` declara el prefijo `api/` una sola vez.

Sin requests ni proveedores: se inspecciona el URLconf raíz. Las apps montan
sus paths sin prefijo dentro de `api_urlpatterns`, así que ninguna ruta de la
API puede quedar fuera de `/api/` ni el prefijo repetirse por app.
"""
from django.urls import URLResolver, reverse

from config import urls


def test_root_urlconf_mounts_admin_and_api_once():
    assert [str(pattern.pattern) for pattern in urls.urlpatterns] == ["django-admin/", "api/"]


def test_api_urlpatterns_never_repeat_the_prefix():
    prefixes = [str(pattern.pattern) for pattern in urls.api_urlpatterns]

    assert not any(prefix.startswith("api/") for prefix in prefixes)
    assert all(
        str(pattern.pattern) == ""
        for pattern in urls.api_urlpatterns
        if isinstance(pattern, URLResolver)
    )


def test_schema_and_docs_stay_under_api():
    assert reverse("api-schema") == "/api/schema/"
    assert reverse("api-docs") == "/api/docs/"
    assert reverse("api-redoc") == "/api/redoc/"
