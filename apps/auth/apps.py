"""Registro de la app de cuentas y acceso (label `accounts`).

El paquete se llama `apps.auth`, pero el label no puede ser `auth`: ese label
ya es de `django.contrib.auth` y Django no admite dos apps con el mismo.
"""
from django.apps import AppConfig


class AuthConfig(AppConfig):
    name = "apps.auth"
    label = "accounts"
    verbose_name = "Accounts"

    def ready(self):
        # Registra la documentación OpenAPI; las views no llevan `@extend_schema`.
        from apps.auth.docs import extensions  # noqa: F401
