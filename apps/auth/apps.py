from django.apps import AppConfig


class AuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.auth"
    # Django deriva la etiqueta del último segmento de `name`, y `auth` ya es
    # la de `django.contrib.auth`. Sin esta línea el proyecto no arranca.
    # Las migraciones y el ContentType usan `tt_auth`, no `auth`. `tt` es
    # TorqueTrack: el prefijo evita el choque sin renombrar el paquete.
    label = "tt_auth"
