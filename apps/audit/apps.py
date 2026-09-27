from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = "apps.audit"

    def ready(self):
        from apps.audit.docs import extensions  # noqa: F401
