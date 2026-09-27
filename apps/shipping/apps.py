from django.apps import AppConfig


class ShippingConfig(AppConfig):
    name = "apps.shipping"

    def ready(self):
        from apps.shipping.docs import extensions  # noqa: F401
