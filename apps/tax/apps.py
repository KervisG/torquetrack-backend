from django.apps import AppConfig


class TaxConfig(AppConfig):
    name = "apps.tax"

    def ready(self):
        from apps.tax.docs import extensions  # noqa: F401
