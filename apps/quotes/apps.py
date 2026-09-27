from django.apps import AppConfig


class QuotesConfig(AppConfig):
    name = "apps.quotes"

    def ready(self):
        from apps.quotes.docs import extensions  # noqa: F401
