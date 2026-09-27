# TorqueTrack Diesel — backend (Django + DRF)

Backend de TorqueTrack: expone la API REST bajo `/api/` y el panel de Django
en `/admin/`. La configuración por entorno vive en
`config/settings/{base,dev,prod}.py`.

La documentación de la API la genera drf-spectacular: Swagger UI en
`/api/docs/`, ReDoc en `/api/redoc/` y el esquema OpenAPI en `/api/schema/`.
Solo la ve el staff con sesión iniciada; un anónimo o un cliente reciben 403.

`apps/` contiene las apps de catálogo, carrito, checkout, cotizaciones, envíos,
impuestos, VIN, fitment y clientes; `authentication` (quién es cada uno: el
`User`, login, sesión y enlaces por correo); `authorization` (quién puede qué:
`Role`, catálogo de permisos, gestión de usuarios y roles del panel, el admin
de Django y el comando `grant_role`); `audit` (la bitácora de
actividad, que las demás apps escriben con `record_activity`) y `dashboard`
(agregados de solo lectura del panel, sin modelos propios); más
`integrations`, que por ahora es un marcador vacío.

## Desarrollo local (Docker)

```bash
docker compose up --build
```

Django queda en `http://localhost:8010` y Postgres en `localhost:5435`.

## Desarrollo local (virtualenv, sin Docker)

```bash
uv venv --python 3.13 .venv   # Python 3.13, fijado en .python-version
.venv/Scripts/activate        # o bien: source .venv/bin/activate
uv pip install -r requirements/dev.txt
python manage.py migrate
```

## Datos iniciales

- `python manage.py import_catalog` carga el catálogo semilla desde
  `apps/catalog/data/`.
- Primer usuario de staff (acceso al panel del SPA). Nadie crea cuentas
  desde el panel ni por terminal: toda persona se registra como cliente y
  después se le asigna un Role.
  1. Crear la cuenta: registrarse en la tienda (`/register` del SPA, que
     llama a `POST /api/register/`) o, en desarrollo,
     `python manage.py createsuperuser` (ya le asigna el Role `admin`).
  2. Asignarle el Role de acceso total:

     ```bash
     python manage.py grant_role --email owner@torquetrackdiesel.com --role admin
     ```

     `--role` es el `slug` de cualquier Role (`admin`, `employee` o uno creado
     en `/admin/`); `--role none` lo quita, salvo que sea el último usuario
     activo con acceso total. No toca la contraseña ni `active` y falla si el
     email no tiene cuenta.
  3. Desde ahí, quien tenga `users.manage` asigna Roles en el panel
     (`/admin/users` del SPA).
- Panel de Django (`/admin/`, donde se crean y editan los Roles): usa la
  misma cuenta que el SPA (`AUTH_USER_MODEL = "authentication.User"`) y solo
  entra un usuario activo con Role de acceso total.

## Recrear la base de desarrollo

La base tiene que ser nueva desde que la app `accounts` se partió en
`authorization` y `authentication` con sus migraciones rehechas desde cero:
en una base vieja `migrate` falla con `InconsistentMigrationHistory`
(`django_migrations` y `django_admin_log` apuntan a la app anterior). Los
datos de desarrollo son desechables.

Con Docker (borra el volumen de Postgres):

```bash
docker compose down -v
docker compose up --build -d
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py import_catalog
docker compose exec backend python manage.py createsuperuser
docker compose exec backend python manage.py grant_role --email owner@torquetrackdiesel.com --role admin
```

Con el Postgres de `localhost:5435` y el virtualenv:

```bash
psql -h localhost -p 5435 -U torquetrack -d postgres \
  -c "DROP DATABASE IF EXISTS torquetrack" -c "CREATE DATABASE torquetrack"
python manage.py migrate
python manage.py import_catalog
python manage.py createsuperuser   # o registrarse en la tienda
python manage.py grant_role --email owner@torquetrackdiesel.com --role admin
```

`grant_role` es redundante tras `createsuperuser` (ya asigna `admin`), pero es
el paso obligatorio si la cuenta se registró en la tienda.

Las sesiones viejas no sobreviven: hay que volver a iniciar sesión.

## Mantenimiento

Los GET del panel son de solo lectura: el listado de cotizaciones calcula el
vencimiento al leer y el de carritos omite los vacíos sin borrarlos. Para
persistir esos cambios hay dos comandos idempotentes, pensados para correr a
mano o desde el cron del host (el proyecto no trae un scheduler):

- `python manage.py expire_quotes` marca `EXPIRED` las cotizaciones abiertas
  (`BUILDING`, `ACTIVE`, `CONTACTED`) cuyo `expires_at` ya pasó.
- `python manage.py purge_carts` borra los carritos sin `items` o con un
  `items` vacío o que no es un array.

## Despliegue

1. Definir las variables de entorno de producción; `env.example` las lista
   todas con su explicación. Las imprescindibles:
   - `DJANGO_SETTINGS_MODULE=config.settings.prod` (`wsgi.py` cae en `dev` si
     no se define).
   - `DJANGO_SECRET_KEY`: aleatoria y de al menos 50 caracteres. `prod.py` no
     arranca (`ImproperlyConfigured`) si falta o es el valor de ejemplo.
   - `DJANGO_ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` con el dominio público
     (el segundo con esquema: `https://...`).
   - `DATABASE_URL` y `DATABASE_SSL`.
   - `APP_URL`, `RESEND_API_KEY` y `FROM_EMAIL`: sin ellas no salen los
     correos de cuenta; `prod.py` lo avisa en el log al arrancar.
   - `CLIENT_IP_HEADER=HTTP_CF_CONNECTING_IP` detrás de Cloudflare.
     **Solo si el origen acepta tráfico exclusivamente desde Cloudflare**
     (allowlist de las IPs de Cloudflare en el firewall o Cloudflare
     Tunnel). Si el origen es alcanzable directo, cualquiera puede mandar ese
     header con una IP inventada y esquivar los rate limits.
   - `CACHE_URL`: opcional. Vacío usa la tabla `django_cache` de Postgres;
     para Redis, `redis://host:6379/1`.
2. `python manage.py migrate`. Además de las tablas de dominio crea la tabla
   del cache compartido (`django_cache`, migración `authentication.0002_cache_table`),
   donde viven los contadores de los throttles: así se comparten entre
   workers y sobreviven a un deploy. Con `CACHE_URL` apuntando a Redis ese
   paso no crea nada.
3. `python manage.py check --deploy` con los settings de producción.
4. La primera vez: registrarse en la tienda y
   `python manage.py grant_role --email ... --role admin`.

Los correos de cuenta (reset de contraseña, verificación) salen en un hilo
aparte del request (`apps/authentication/utils/background.py`) para que el tiempo de
respuesta no revele qué correos tienen cuenta. No hay reintentos: si el
proceso se reinicia en medio de un envío, ese correo se pierde y la persona
lo vuelve a pedir.

## Tests

```bash
pytest
```

Los tests que renderizan el PDF con WeasyPrint se saltan (`skipped`) cuando faltan las librerías nativas de GTK/Pango, como en Windows; en el contenedor de `Dockerfile` corren completos.
