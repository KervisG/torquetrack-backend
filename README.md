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