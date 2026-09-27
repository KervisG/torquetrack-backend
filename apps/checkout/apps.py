from django.apps import AppConfig


class CheckoutConfig(AppConfig):
    name = "apps.checkout"

    def ready(self):
        # Registra la documentación OpenAPI; las views no llevan `@extend_schema`.
        from apps.checkout.docs import extensions  # noqa: F401
