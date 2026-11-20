from django.apps import AppConfig


class RolesConfig(AppConfig):
    name = "apps.roles"
    label = "roles"
    verbose_name = "Roles"

    def ready(self):
        # Registra la documentación OpenAPI; las views no llevan `@extend_schema`.
        from apps.roles.docs import extensions  # noqa: F401
