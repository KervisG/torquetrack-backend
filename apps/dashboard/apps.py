from django.apps import AppConfig


class DashboardConfig(AppConfig):
    name = "apps.dashboard"

    def ready(self):
        from apps.dashboard.docs import extensions  # noqa: F401
