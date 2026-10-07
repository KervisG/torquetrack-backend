# Dos targets: `dev` (docker compose: runserver y dependencias de tests) y
# `prod` (el último, así que `docker build .` construye producción: gunicorn,
# estáticos recolectados y usuario sin privilegios).
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    # WeasyPrint (PDF de cotizaciones) necesita Pango/Cairo/GDK-Pixbuf para
    # maquetar y renderizar el PDF a partir de HTML y CSS; ninguna otra app
    # las usa, por eso no van en la línea de `build-essential`.
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
    libharfbuzz-subset0 fonts-dejavu-core fontconfig \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip


FROM base AS dev

ENV DJANGO_SETTINGS_MODULE=config.settings.dev

COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/dev.txt

COPY . .

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


FROM base AS prod

COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/base.txt

COPY . .

# `prod.py` valida `DJANGO_SECRET_KEY`, `APP_URL` y `CELERY_BROKER_URL` al
# importarse. Estos valores ficticios existen solo durante este RUN (no quedan
# en el `ENV` de la imagen) y `collectstatic` no firma nada ni se conecta a la
# base ni al broker.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=build-only-collectstatic-placeholder-not-a-real-secret-0123456789 \
    APP_URL=https://build.invalid \
    CELERY_BROKER_URL=redis://build.invalid:6379/0 \
    python manage.py collectstatic --noinput

# Con home propio: fontconfig (WeasyPrint) guarda ahí su caché de fuentes.
RUN useradd --system --create-home --uid 10001 app
USER app

ENV DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8000

EXPOSE 8000

# La misma imagen corre el worker y beat de Celery cambiando el comando (un
# proceso por contenedor, sin supervisor):
#   worker: celery -A config worker -l info
#   beat:   celery -A config beat -l info -s /tmp/celerybeat-schedule
# Beat necesita `-s` en una ruta escribible: `/app` es de root y el proceso
# corre como `app`. Una sola instancia de beat, o cada trabajo sale dos veces.
#
# Timeout de 60 s: el PDF de la cotización (WeasyPrint) se renderiza dentro del
# request. `WEB_CONCURRENCY` ajusta los workers según la RAM del hosting.
#
# `migrate` corre en cada arranque: el plan gratuito de Render no tiene
# pre-deploy ni shell. Si no hay migraciones pendientes, no hace nada.
# `import_catalog --if-empty` carga la semilla solo si no hay productos; si
# falla (por ejemplo, un precio en 0) se registra y el servidor arranca igual.
CMD ["sh", "-c", "python manage.py migrate --noinput && (python manage.py import_catalog --if-empty || echo 'import_catalog failed: catalog not loaded') && exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-3} --timeout 60 --access-logfile -"]
