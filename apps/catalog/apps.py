from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "apps.catalog"

    def ready(self):
        from apps.catalog.docs import extensions  # noqa: F401
