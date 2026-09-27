from django.apps import AppConfig


class FitmentConfig(AppConfig):
    name = "apps.fitment"

    def ready(self):
        from apps.fitment.docs import extensions  # noqa: F401
