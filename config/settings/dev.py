from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Sin broker (sin Redis local) `.delay()` intentaría `amqp://localhost`: la
# tarea corre en el proceso y su error sube al que la llamó. Con
# `CELERY_BROKER_URL` definido (docker compose) va al worker como en producción.
CELERY_TASK_ALWAYS_EAGER = not CELERY_BROKER_URL  # noqa: F405
CELERY_TASK_EAGER_PROPAGATES = True
