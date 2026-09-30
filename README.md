# TorqueTrack Diesel — backend

API REST de la tienda TorqueTrack Diesel, hecha con Django + DRF sobre
PostgreSQL. El frontend vive en el repo `torquetrack-frontend`.

## Requisitos

- Docker, o Python 3.13 con [uv](https://docs.astral.sh/uv/)
- PostgreSQL (lo trae el `docker-compose.yml`)

## Levantar en local

Con Docker:

```bash
docker compose up --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py import_catalog
```

Sin Docker:

```bash
uv venv --python 3.13 .venv
source .venv/bin/activate      # Windows: .venv/Scripts/activate
uv pip install -r requirements/dev.txt
python manage.py migrate
python manage.py import_catalog
python manage.py runserver
```

La API queda en `http://localhost:8010` (Docker) o `http://localhost:8000`.
Copia `.env.example` a `.env` y ajusta los valores.

## Tareas programadas (Celery)

`docker compose up` también levanta `redis`, `worker` y `beat`. Beat encola
`expire_quotes` cada hora y `purge_carts` todos los días a las 03:30 UTC; los
comandos `manage.py expire_quotes` y `manage.py purge_carts` siguen sirviendo
para correrlos a mano. El worker y beat no recargan el código: tras cambiar una
tarea, `docker compose restart worker beat`.

Sin Docker, con el Redis del compose (`docker compose up -d redis`, puerto 6385)
y `CELERY_BROKER_URL=redis://localhost:6385/0` en `.env`:

```bash
celery -A config worker -l info --pool=solo   # --pool=solo en Windows
celery -A config beat -l info
```

Sin `CELERY_BROKER_URL`, en desarrollo las tareas corren en el mismo proceso.

Variables de entorno:

- `CELERY_BROKER_URL`: broker de Celery (`redis://host:6379/0`). Obligatoria en
  producción; vacía en desarrollo corre las tareas en el proceso.
- `CACHE_URL`: cache de Django (`redis://host:6379/1`). Vacía usa la tabla
  `django_cache` de Postgres.

En producción la misma imagen corre cada proceso cambiando el comando:

```bash
celery -A config worker -l info
celery -A config beat -l info -s /tmp/celerybeat-schedule
```

Una sola instancia de beat; `-s` apunta a una ruta escribible porque la imagen
corre sin privilegios.

## Primer usuario admin

```bash
python manage.py createsuperuser
```

Si la cuenta se creó registrándose en la tienda, asígnale el rol de admin:

```bash
python manage.py grant_role --email tu@correo.com --role admin
```

## Recrear la base de desarrollo

Si `migrate` falla con `InconsistentMigrationHistory` (base anterior a la
separación de `accounts`), borra la base y repite los pasos de arriba:

```bash
docker compose down -v && docker compose up --build -d
```

## Tests

```bash
pytest
```

Necesita el Postgres de Docker encendido (`docker compose up -d db`). Los
tests del PDF se saltan en Windows porque faltan las librerías de WeasyPrint.

## Documentación

- API: `/api/docs/` (Swagger) y `/api/redoc/`, solo con sesión de staff.
- Convenciones del código: `AGENTS.md` y `skills/`.

redis