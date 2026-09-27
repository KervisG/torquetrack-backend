from django.apps import AppConfig


class HealthConfig(AppConfig):
    name = "apps.health"

    def ready(self):
        from apps.health.docs import extensions  # noqa: F401
