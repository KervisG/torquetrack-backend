# TorqueTrack Diesel — backend (Django + DRF)

Backend de TorqueTrack: expone la API REST bajo `/api/` y el panel de Django
en `/admin/`. La configuración por entorno vive en
`config/settings/{base,dev,prod}.py`.

`apps/` contiene las apps de catálogo, carrito, checkout, cotizaciones, envíos,
impuestos, VIN, fitment, clientes y autenticación; `audit` (la bitácora de
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
- Primer usuario de staff (acceso al panel del SPA):

  ```bash
  python manage.py create_admin --email owner@torquetrackdiesel.com
  ```

  Crea la cuenta con el Role `admin` (acceso total) y el email ya verificado,
  o asciende una cuenta existente. Sin `--password` pide la contraseña por la
  terminal (así no queda en el historial del shell) y la valida con
  `AUTH_PASSWORD_VALIDATORS`; en una cuenta existente, omitirla deja la
  contraseña como está. Es idempotente. En un entorno sin terminal (CI, job
  de deploy) pasar `--password`.
- Panel de Django (`/admin/`, donde se crean y editan los Roles): usa el
  usuario de `django.contrib.auth`, que es otro que la cuenta del SPA.
  Crearlo con `python manage.py createsuperuser` solo si hace falta entrar
  ahí.

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
   del cache compartido (`django_cache`, migración `tt_auth.0010_cache_table`),
   donde viven los contadores de los throttles: así se comparten entre
   workers y sobreviven a un deploy. Con `CACHE_URL` apuntando a Redis ese
   paso no crea nada.
3. `python manage.py check --deploy` con los settings de producción.
4. `python manage.py create_admin --email ...` la primera vez.

Los correos de cuenta (reset de contraseña, verificación) salen en un hilo
aparte del request (`apps/auth/utils/background.py`) para que el tiempo de
respuesta no revele qué correos tienen cuenta. No hay reintentos: si el
proceso se reinicia en medio de un envío, ese correo se pierde y la persona
lo vuelve a pedir.

## Tests

```bash
pytest
```

Los tests que renderizan el PDF con WeasyPrint se saltan (`skipped`) cuando faltan las librerías nativas de GTK/Pango, como en Windows; en el contenedor de `Dockerfile` corren completos.
