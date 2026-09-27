from django.apps import AppConfig


class CustomersConfig(AppConfig):
    name = "apps.customers"

    def ready(self):
        from apps.customers.docs import extensions  # noqa: F401
