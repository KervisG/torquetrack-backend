"""Toda view de DRF declara `permission_classes` y el default queda cerrado.

`DEFAULT_PERMISSION_CLASSES` es `HasRolePermission` (solo staff): una view que
olvide declarar permisos no se abre al público, pero el default tampoco decide
por olvido. El primer test recorre el URLconf entero y falla si alguna view de
DRF hereda `permission_classes` directo de DRF (es decir, del default). Sin
proveedores que mockear.
"""
import pytest
from django.conf import settings
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from tests.factories import create_staff_user, create_user


def _url_patterns(resolver=None, prefix=""):
    resolver = resolver or get_resolver()
    for entry in resolver.url_patterns:
        if isinstance(entry, URLResolver):
            yield from _url_patterns(entry, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            yield prefix + str(entry.pattern), entry.callback


def _drf_view_class(callback):
    """`as_view()` de DRF (APIView y ViewSet) deja la clase en `cls`."""
    cls = getattr(callback, "cls", None)
    if isinstance(cls, type) and issubclass(cls, APIView):
        return cls
    return None


def _declares_permissions(cls) -> bool:
    """Cuenta la declaración en la propia clase o en una base del proyecto (o
    de drf-spectacular); nunca la que viene de `rest_framework`, que es el
    default de settings."""
    return any(
        "permission_classes" in vars(klass)
        for klass in cls.__mro__
        if not klass.__module__.startswith("rest_framework")
    )


def test_default_permission_class_is_staff_only():
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "apps.authorization.permissions.HasRolePermission"
    ]


def test_every_drf_view_declares_permission_classes_explicitly():
    views = {
        (route, cls)
        for route, callback in _url_patterns()
        if (cls := _drf_view_class(callback)) is not None
    }
    # Sanidad: el recorrido encuentra las views de verdad.
    assert len(views) > 40

    undeclared = sorted(
        f"{route} -> {cls.__module__}.{cls.__qualname__}"
        for route, cls in views
        if not _declares_permissions(cls)
    )
    assert undeclared == []


class _ForgotPermissionsView(APIView):
    def get(self, request):
        return Response({"ok": True})


def _call(user=None):
    request = APIRequestFactory().get("/probe/")
    if user is not None:
        force_authenticate(request, user=user)
    return _ForgotPermissionsView.as_view()(request)


@pytest.mark.django_db
def test_view_without_permission_classes_rejects_anonymous_visitors():
    response = _call()

    assert response.status_code == 403
    assert response.data == {"error": "You do not have permission to perform this action."}


@pytest.mark.django_db
def test_view_without_permission_classes_rejects_customers():
    response = _call(create_user("U_FORGOT_CUSTOMER"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_view_without_permission_classes_admits_staff():
    response = _call(create_staff_user("U_FORGOT_STAFF"))

    assert response.status_code == 200
