from django.apps import AppConfig


class AuthorizationConfig(AppConfig):
    name = "apps.authorization"

    def ready(self):
        # Registra la documentación OpenAPI; las views no llevan `@extend_schema`.
        from apps.authorization.docs import extensions  # noqa: F401
