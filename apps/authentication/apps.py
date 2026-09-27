from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    name = "apps.authentication"

    def ready(self):
        # Registra la documentación OpenAPI; las views no llevan `@extend_schema`.
        from apps.authentication.docs import extensions  # noqa: F401
