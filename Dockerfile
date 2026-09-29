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

# `prod.py` valida `DJANGO_SECRET_KEY` y `APP_URL` al importarse. Estos valores
# ficticios existen solo durante este RUN (no quedan en el `ENV` de la imagen)
# y `collectstatic` no firma nada ni se conecta a la base.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=build-only-collectstatic-placeholder-not-a-real-secret-0123456789 \
    APP_URL=https://build.invalid \
    python manage.py collectstatic --noinput

# Con home propio: fontconfig (WeasyPrint) guarda ahí su caché de fuentes.
RUN useradd --system --create-home --uid 10001 app
USER app

ENV DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8000

EXPOSE 8000

# Timeout de 60 s: el PDF de la cotización (WeasyPrint) se renderiza dentro del
# request. `WEB_CONCURRENCY` ajusta los workers según la RAM del hosting.
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-3} --timeout 60 --access-logfile -"]
