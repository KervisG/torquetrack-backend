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
(agregados de solo lectura del panel, sin modelos propios); `integrations`
(adaptadores de proveedores externos) y `health` (`GET /api/health/`).

## Contrato común de la API

- **Permisos cerrados por defecto.** `DEFAULT_PERMISSION_CLASSES` es
  `HasRolePermission` (solo staff): una view que olvide declarar permisos no
  queda pública. Igual toda view declara `permission_classes` explícito
  (`AllowAny` las públicas y las que separan 401 de 403 a mano);
  `tests/test_view_permissions.py` recorre el URLconf y falla si alguna no lo
  declara.
- **Un solo formato de error.** Todo error es `{"error": "<mensaje>"}`, también
  los que arma DRF (401, 403, 404, 405, 415, 429, JSON mal formado, CSRF):
  `config/exceptions.py` (`EXCEPTION_HANDLER`) cambia `detail` por `error` y
  conserva el código y los headers (`Retry-After`, `Allow`,
  `WWW-Authenticate`). Un error de validación por campo agrega
  `"fields": {...}` y lleva el primer mensaje en `error`. Nunca responder
  `{"detail": ...}`.
- **Health check.** `GET /api/health/` es público, sin sesión ni throttle:
  `200 {"ok": true}` si la base responde y `503 {"ok": false, "error":
  "Database unavailable"}` si no. En producción está exento del redirect a
  HTTPS.
- **Envío de pedidos.** `POST /api/admin/orders/<id>/fulfillment/` (permiso
  `orders.status`) mueve el envío, que va separado de `status`:
  `UNFULFILLED -> PREPARING -> SHIPPED -> DELIVERED`, solo hacia adelante y con
  el salto `UNFULFILLED -> SHIPPED`. Solo avanza un pedido cobrado (`PAID` o
  `PARTIALLY_REFUNDED`) y no cerrado (409). `SHIPPED` exige `carrier` (`UPS`,
  `FEDEX`, `USPS`, `OTHER`) y `trackingNumber` (1 a 64 letras, dígitos o
  guiones; 400) y avisa al cliente por correo con el enlace de seguimiento;
  repetirlo con otra guía la corrige y vuelve a avisar. `DELIVERED` exige
  `SHIPPED`. El listado del panel y `GET /api/account/orders/` devuelven
  `fulfillmentStatus`, `carrier`, `trackingNumber`, `trackingUrl`, `shippedAt` y
  `deliveredAt`. Cada cambio queda en la bitácora (`FULFILLMENT_UPDATED`).
- **Logging.** Todo sale por consola con `fecha nivel logger mensaje`; el
  nivel raíz sale de `LOG_LEVEL` (`INFO` por defecto), `django.request` queda
  en `WARNING` y los loggers `apps.*` propagan al root. Nunca loguear tokens,
  contraseñas ni datos personales.

## Desarrollo local (Docker)

```bash
docker compose up --build
```

Django queda en `http://localhost:8010` y Postgres en `localhost:5435`. El
servicio `backend` usa el target `dev` del `Dockerfile` (runserver y
dependencias de tests); el target por defecto es producción.

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

## Carrito

El backend es la fuente de verdad del carrito (`apps/cart/`). Con sesión
iniciada el carrito es el de la cuenta (`Cart.user`, uno por cuenta) y se ve
igual en cualquier dispositivo; un invitado usa el carrito de su sesión
(`cart_id`). El SPA lo lee con `GET /api/cart/` y lo reemplaza con
`PUT /api/cart/` (`{"items": [{"id", "qty"}]}`: producto activo, cantidad
entera de 1 a 99, cada producto una vez). Toda respuesta reprecia desde el
catálogo e ignora cualquier precio del cliente.

Al iniciar sesión (login, activación del portal) la señal `user_logged_in`
fusiona el carrito invitado con el de la cuenta: suma las cantidades del mismo
producto con tope 99, agrega los distintos y borra el invitado. Al cerrar
sesión el carrito queda en la cuenta y la sesión nueva empieza vacía.

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

La imagen de producción es el target por defecto del `Dockerfile`:

```bash
docker build -t torquetrack-backend .
```

Instala solo `requirements/base.txt`, corre `collectstatic` al construir
(WhiteNoise sirve `/static/` con nombres con hash y comprimidos), arranca con
un usuario sin privilegios y ejecuta gunicorn en `0.0.0.0:$PORT` (8000 por
defecto; `WEB_CONCURRENCY` fija los workers, 3 por defecto; timeout de 60 s
por el PDF de WeasyPrint). `migrate` no corre solo: va como paso de release.

1. Definir las variables de entorno de producción; `.env.example` las lista
   todas con su explicación. Las imprescindibles:
   - `DJANGO_SETTINGS_MODULE=config.settings.prod`: la imagen ya lo define y
     `wsgi.py`/`asgi.py` caen en `prod` si falta (`manage.py` sigue cayendo
     en `dev` para el uso local).
   - `DJANGO_SECRET_KEY`: aleatoria y de al menos 50 caracteres. `prod.py` no
     arranca (`ImproperlyConfigured`) si falta o es el valor de ejemplo.
   - `APP_URL`: URL `https://` del SPA. `prod.py` no arranca
     (`ImproperlyConfigured`) si falta o no es HTTPS; de ella salen el retorno
     de Stripe y los enlaces de los correos.
   - `DJANGO_ALLOWED_HOSTS` con el dominio público. `CSRF_TRUSTED_ORIGINS`
     es opcional: por defecto es el origen de `APP_URL` (con esquema:
     `https://...`).
   - `DATABASE_URL` y `DATABASE_SSL`.
   - `RESEND_API_KEY` y `FROM_EMAIL`: sin ellas no salen los correos de
     cuenta; `prod.py` lo avisa en el log al arrancar.
   - `CLIENT_IP_HEADER=HTTP_CF_CONNECTING_IP` detrás de Cloudflare.
     **Solo si el origen acepta tráfico exclusivamente desde Cloudflare**
     (allowlist de las IPs de Cloudflare en el firewall o Cloudflare
     Tunnel). Si el origen es alcanzable directo, cualquiera puede mandar ese
     header con una IP inventada y esquivar los rate limits.
   - `CACHE_URL`: opcional. Vacío usa la tabla `django_cache` de Postgres;
     para Redis, `redis://host:6379/1`.
   - HTTPS: `prod.py` redirige a HTTPS (`SECURE_SSL_REDIRECT`, exento
     `/api/health/`), manda HSTS de un año con subdominios
     (`SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`) y deja el
     preload en `false` (`SECURE_HSTS_PRELOAD`). Detrás de un proxy que
     termina TLS, `USE_X_FORWARDED_PROTO=true` (si no, el redirect entra en
     bucle); solo si el proxy siempre escribe `X-Forwarded-Proto` y el origen
     no es alcanzable sin pasar por él.
   - `SALES_EMAIL`, `COMPANY_ADDRESS` (por defecto `Sarasota, FL`) y
     `APP_URL` arman el pie de la cotización (página, correo y PDF);
     `SHIP_FROM_ZIP` (por defecto `34241`) es el origen de envíos e
     impuestos. `LOG_LEVEL` fija el nivel del log.
2. `python manage.py migrate`. Además de las tablas de dominio crea la tabla
   del cache compartido (`django_cache`, migración `authentication.0002_cache_table`),
   donde viven los contadores de los throttles: así se comparten entre
   workers y sobreviven a un deploy. Con `CACHE_URL` apuntando a Redis ese
   paso no crea nada.
3. `python manage.py check --deploy` con los settings de producción. Queda
   solo `security.W021` (preload de HSTS apagado a propósito) y los avisos
   `drf_spectacular.W00x` de las views sin documentar.
4. Apuntar el health check del hosting a `/api/health/`. El `Host` del ping
   tiene que estar en `DJANGO_ALLOWED_HOSTS` o Django responde 400.
5. La primera vez: registrarse en la tienda (el registro no inicia sesión:
   hay que entrar después desde `/login`) y
   `python manage.py grant_role --email ... --role admin`.
6. Webhook de Stripe: en el dashboard de Stripe (Developers → Webhooks) crear
   el endpoint `https://<dominio>/api/webhooks/stripe/`, copiar su signing
   secret en `STRIPE_WEBHOOK_SECRET` y activar estos eventos:
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
   `checkout.session.async_payment_failed`, `checkout.session.expired`,
   `refund.created`, `refund.updated`, `refund.failed` y `charge.refunded`.
   Sin `checkout.session.expired` los pedidos `PENDING_PAYMENT` cuya sesión
   venció sin pagarse quedan pendientes para siempre; con él, el pago pasa a
   `CANCELLED` y el pedido a `CANCELLED` (bitácora `ORDER_EXPIRED`), y una
   cotización con ese pedido vuelve a poder pagarse.

Los correos de cuenta (reset de contraseña, verificación y el aviso "You
already have a TorqueTrack account" de un registro con un email ya
registrado) salen en un hilo
aparte del request (`apps/authentication/utils/background.py`) para que el tiempo de
respuesta no revele qué correos tienen cuenta. No hay reintentos: si el
proceso se reinicia en medio de un envío, ese correo se pierde y la persona
lo vuelve a pedir.

## Tests

```bash
pytest
```

Los tests que renderizan el PDF con WeasyPrint se saltan (`skipped`) cuando faltan las librerías nativas de GTK/Pango, como en Windows; en el contenedor de `Dockerfile` corren completos.
