---
name: backend-testing
description: "Trigger: escribir tests, pytest, test de endpoint, mockear stripe, fixtures, factories, migraciones. Patrones de pytest del backend Django."
license: Apache-2.0
metadata:
  author: Kervis
  version: "1.7"
---

## Activation Contract

Cargar antes de escribir o cambiar cualquier test en este repo.

Correr desde la raíz del repo: `python -m pytest apps/<app>` para una app, `python -m pytest` para todo. Los settings salen de `pytest.ini` (`config.settings.dev`).

## Hard Rules

- Los tests por app van en `apps/<app>/tests/` como paquete con `__init__.py`. Las garantías que cruzan apps van en `tests/`. Los helpers de `apps/common/` (que no es una app de Django) se prueban en `apps/common/tests/`, sin base de datos salvo que el helper lea `settings`.
- Nombrar el módulo según la superficie que prueba, no según la ruta del archivo: `test_models.py`, `test_views.py` (storefront, o la única superficie de la app), `test_admin_views.py` (panel, aunque las views vivan en `views/admin.py` o en el `views.py` de una app solo de panel), o uno específico como `test_stripe_webhook_view.py`. Mover código entre `views/` o `services/` no renombra tests.
- El docstring del módulo nombra la ruta de la API que prueba, la estrategia de mocking y cualquier regla no obvia que asserte a propósito.
- **Arrange y assert con el ORM.** Todas las tablas son de Django y la base de test sale solo de `migrate`, así que las filas se crean con `Model.objects.create(...)`. Cuentas, roles y perfiles salen de `tests/factories.py` (`create_user`, `create_staff_user`, `create_role`, `create_customer`); pedidos, cotizaciones, productos y carritos, de helpers `_insert_*` del módulo que llaman al ORM. Nunca `connection.cursor()` para armar datos; las únicas excepciones son un test que pruebe un `db_default` con un `INSERT` fuera del ORM, uno que pruebe el `ON DELETE` de una FK con un `DELETE` fuera del ORM (`tests/test_db_on_delete.py`) y la introspección del esquema.
- Ningún test puede llegar a una API de terceros real. Assertear también lo negativo: cuando un camino NO debe llamar a un proveedor, monkeypatchearlo para que lance excepción.
- **Los tests de dominio parchean el adaptador, nunca `requests` ni el SDK.** El path es el del adaptador (`apps.integrations.tax.taxjar.calculate_tax`, `apps.integrations.payments.stripe.create_checkout_session`), que funciona porque los services llaman `modulo.funcion(...)`. El request HTTP, el caso sin key y el mapeo de errores se prueban una sola vez en `apps/integrations/tests/test_<proveedor>.py`, parcheando `requests.post` del adaptador o el SDK.
- **Parchear el módulo donde se usa la función, no el `__init__` que la reexporta.** Todo `services/` es un paquete y cada módulo tiene su propia referencia: el hilo de los correos de cuenta se parchea en `apps.authentication.services.tokens.run_in_background`, no en `apps.authentication.services.run_in_background` (el correo "has shipped" del envío, en `apps.checkout.services.fulfillment.run_in_background`); el PDF adjunto de una cotización en `apps.quotes.services.pdf.render_quote_pdf_base64`; el tope del certificado en `apps.customers.services.storefront.MAX_CERTIFICATE_BYTES`. Al mover una función entre módulos, mover también el target de cada `monkeypatch.setattr` y comprobar que el parche sigue surtiendo efecto (un parche que lanza excepción tiene que hacer fallar el camino que lo usa). Lo mismo para `caplog.at_level(logger=...)`: el logger es `__name__` del módulo concreto (`apps.checkout.services.payments`).
- Para Resend usar `tests/fakes.py`: `install_resend(monkeypatch)` devuelve un `FakeResend` con `.sent` (cada correo con `to` como lista), `SlowResend` prueba que el request no espera al proveedor y `forbid_resend(monkeypatch)` hace fallar cualquier envío.
- Usar el fixture `settings` o `override_settings` para las keys de proveedores. Nunca una key real; usar un valor obviamente falso como `"tj_test_fake"`.
- `DEBUG` es `False` bajo pytest aunque `config.settings.dev` lo ponga en `True`. Todo test que dependa de eso tiene que fijarlo explícitamente con `override_settings(DEBUG=...)`.
- Autenticar un request con `session_client(user_id)` de `tests/factories.py` (hace `force_login` del `User`, que pasa por `django.contrib.auth.login()`; el usuario tiene que existir antes), o llamando a `POST /api/login/`. Para probar que una sesión dejó de valer, pedir `GET /api/session/` con ese cliente y esperar 401; no buscar filas de `django_session`. Staff es un `User` con Role; un `User` sin Role es cliente. Nunca saltear la permission class.
- `APIClient` no exige CSRF por defecto; para probarlo usar `session_client(user_id, enforce_csrf=True)`.
- **Errores.** Todo error se assertea como `{"error": ...}`, también los de DRF (403 de permiso, 405, 415, 429, JSON mal formado, CSRF): nunca `response.json()["detail"]`. `tests/test_error_format.py` prueba el handler (`config/exceptions.py`) y que `Retry-After`/`Allow`/`WWW-Authenticate` sobreviven.
- **Permisos.** Una view de prueba definida en un test hereda el default `HasRolePermission` (solo staff): declararle `permission_classes` si el test necesita otra cosa. `tests/test_view_permissions.py` falla si una view del URLconf no declara `permission_classes`.
- **Settings.** Los settings que se leen al importar (`prod.py`, `LOGGING`, `COMPANY_ADDRESS`, `SHIP_FROM_ZIP`) se prueban recargando el módulo con `_load_prod`/`_load_base` de `tests/test_settings.py`, borrando antes las variables de entorno que el test no fija. Un test que aplique `logging.config.dictConfig` restaura `settings.LOGGING` al terminar.
- **Base caída.** El 503 de `/api/health/` se prueba parcheando `apps.health.views.database_is_available`, o reemplazando `apps.health.services.database.connection` por un doble; nunca cerrando ni rompiendo la conexión real de los tests.
- Limpiar el cache alrededor de cualquier test que toque un endpoint con throttle; `SimpleRateThrottle` guarda sus contadores en el cache compartido y los filtra entre tests. El cache es `DatabaseCache` (tabla `django_cache`), así que el fixture que llama a `cache.clear()` pide `db`.
- `SimpleRateThrottle.THROTTLE_RATES` se resuelve al importar, así que `override_settings(REST_FRAMEWORK=...)` no cambia un rate. Fijar `rate` en la clase del throttle en su lugar. `LoginAccountRateThrottle` suma solo los logins fallidos: para llegar a su tope, mandar contraseñas incorrectas.
- Una tabla nueva de dominio se agrega a `DOMAIN_TABLES` en `tests/test_migrations.py`.
- Para assertear que una acción dejó rastro en la bitácora, usar `activity_count(action=..., entity_id=...)` de `tests/factories.py`. Fuera de `apps/audit/` ningún módulo (tampoco un test) importa `ActivityLog`; `tests/test_audit_boundary.py` lo verifica.
- Para probar una carrera real (por ejemplo la numeración de pedidos) usar `@pytest.mark.django_db(transaction=True)` con hilos y cerrar las conexiones de cada hilo con `connections.close_all()`. Ver `apps/checkout/tests/test_document_numbers.py`.

## Decision Gates

| Qué estás falseando | Cómo |
|---|---|
| Un proveedor desde un test de dominio | `monkeypatch.setattr` sobre la función del adaptador (`apps.integrations.<capacidad>.<proveedor>.<función>`) devolviendo el dict plano, o lanzando `ProviderError` |
| Correo de Resend desde un test de dominio | `install_resend` / `forbid_resend` de `tests/fakes.py` |
| El HTTP de un adaptador REST (TaxJar, EasyPost, Resend) | `monkeypatch` sobre `apps.integrations.<capacidad>.<proveedor>.requests.post` en `apps/integrations/tests/` |
| El HTTP de NHTSA en su adaptador | la librería `responses` (`@responses.activate`) |
| Verificación de firma de Stripe | SDK real a través de `construct_webhook_event`; calcular un HMAC `t=,v1=` válido en el test |
| Llamada de red del SDK de Stripe en su adaptador | `monkeypatch` sobre `stripe.checkout.Session.create` / `stripe.PaymentIntent.retrieve` |
| Un proveedor que no debe ser llamado en absoluto | `monkeypatch` a una función que lance `AssertionError` |
| Key de proveedor ausente | `settings.<KEY> = ""` |

## Execution Steps

1. Leer la view y el service de Django, después listar los casos: camino feliz, cada error de validación, cada nivel de permiso, cada fallo de proveedor.
2. Escribir el docstring del módulo nombrando la ruta de la API y la estrategia de mocking.
3. Agregar los helpers de arrange con el ORM arriba del módulo.
4. Un test por caso, enfocado en el assert; assertear el código de estado y la forma del body, no solo el status.
5. Correr `python -m pytest apps/<app> -q` y `python -m ruff check .`.

## Output Contract

Reportar los módulos de test tocados, la cantidad de casos, qué se mockeó y en qué path de import, y el total de pasados/fallados. Señalar cualquier fallo preexistente y probar que es preexistente antes de atribuirlo a otra cosa.

## References

- `references/fixtures.md` — cómo se arma la base de test, helpers de arrange y los fallos conocidos de entorno.
