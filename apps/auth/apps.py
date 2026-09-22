from django.apps import AppConfig


class AuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.auth"
    # Django deriva la etiqueta del último segmento de `name`, y `auth` ya es
    # la de `django.contrib.auth`, que no se puede sacar porque el RBAC usa
    # sus tablas `Permission` y `Group`. Sin esta línea el proyecto no
    # arranca: `Application labels aren't unique, duplicates: auth`.
    #
    # La etiqueta casi no se usa: esta app no tiene modelos ni migraciones,
    # así que no aparece en dependencias de migración ni en `get_model`.
    label = "tt_auth"
