from django.apps import AppConfig


class VinConfig(AppConfig):
    name = "apps.vin"

    def ready(self):
        from apps.vin.docs import extensions  # noqa: F401
