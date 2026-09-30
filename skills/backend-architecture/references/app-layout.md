# Organización de `apps/`

## Estructura de una app

En la raíz de `apps/<app>/` solo pueden quedar estos archivos:

| Archivo | Cuándo |
|---|---|
| `__init__.py` | siempre |
| `apps.py` | siempre: `AppConfig` con `name = "apps.<domain>"` |
| `urls.py` | si la app expone endpoints (`numbering` e `integrations` no tienen) |
| `admin.py` | solo si registra modelos en el admin de Django (hoy, solo `authorization`) |
| `views.py` | solo si la app tiene UNA sola superficie |

Todo lo demás vive en carpetas:

| Carpeta | Contenido |
|---|---|
| `models/` | Un módulo por modelo (`models/order.py`, `models/payment.py`); `__init__.py` los reexporta con `__all__` |
| `services/` | Reglas de negocio, un módulo por tema; `__init__.py` reexporta la API pública con `__all__` (ver "Cómo se parte `services/`") |
| `views/` | SOLO con más de una superficie: `views/storefront.py`, `views/admin.py`, `views/webhooks.py`, `views/pdf.py`; `__init__.py` reexporta con `__all__` y no queda `views.py` en la raíz |
| `serializers/` | Serializers de DRF de los `ModelViewSet`, un módulo por superficie (`serializers/storefront.py`) |
| `permissions/` | Catálogo de permisos y clases DRF (`apps/authorization/permissions/`) |
| `utils/` | Helpers que no son service ni view (hasher, throttle, hilos en segundo plano) |
| `docs/` | Documentación OpenAPI (ver "Documentación OpenAPI") |
| `migrations/` | Migraciones de `makemigrations` |
| `tests/` | Paquete, un módulo por superficie |
| `management/commands/` | Comandos de `manage.py` |
| `templates/<app>/` | Plantillas de Django (`quotes/templates/quotes/quote.html`) |
| `data/` | Datos de carga que lee un comando (`catalog/data/`) |

Reglas:

- **Superficie** es un consumidor distinto de la API: el storefront público (incluye el portal del cliente, `/api/account/**`), el panel (`/api/admin/**`), los webhooks de un proveedor y las descargas binarias (PDF, que además aíslan la dependencia de WeasyPrint). Con una sola superficie, sus endpoints van en `views.py` en la raíz, aunque sea el panel (`authorization`, `audit`, `dashboard`). Con más de una, cada superficie tiene su módulo en `views/` y nunca comparten módulo.
- Ningún archivo de la raíz lleva prefijo de superficie (`admin_views.py`, `admin_services.py`, `webhook_views.py`, `pdf_views.py`): lo reemplazan `views/admin.py`, `views/webhooks.py`, `views/pdf.py` y `services/admin.py`. `pdf.py` y los demás módulos de lógica van a `services/`.
- Nunca crear una carpeta vacía ni un `__init__.py` sin módulos al lado. Nunca `logic/`, `core/`, `domain/`, `helpers/` ni `constants/`: una constante vive en el módulo que la usa o que es dueño de su tema.
- Mover un modelo entre módulos de `models/` no cambia su `app_label` (sale del paquete de la app) ni su `db_table` (explícito en `Meta`), así que no genera migraciones. Si `makemigrations` detecta un cambio, el movimiento está mal.
- Los tests se nombran por superficie (`test_views.py`, `test_admin_views.py`, `test_stripe_webhook_view.py`), no por la ruta del archivo que prueban.

Excepciones documentadas:

- `apps/common/` no es una app de Django (sin `apps.py`, modelos, views, urls ni migraciones): es un paquete de helpers sin estado y conserva sus módulos planos (`ids.py`, `links.py`, `numbers.py`, `tokens.py`).
- `apps/integrations/exceptions.py` queda en la raíz porque es el contrato compartido de todos los adaptadores; los adaptadores viven en carpetas por capacidad (`email/`, `payments/`, `shipping/`, `tax/`, `vehicles/`).

Ejemplo de una app con tres superficies (storefront, panel y webhook de Stripe):

```text
apps/checkout/
├── __init__.py
├── apps.py
├── urls.py
├── models/
│   ├── __init__.py             # reexporta Order, Payment y Refund con __all__
│   ├── order.py
│   ├── payment.py
│   └── refund.py               # tabla `refunds`, FK CASCADE a Payment
├── services/
│   ├── __init__.py             # reexporta la API pública con __all__
│   ├── payments.py             # único dueño de las sesiones de Stripe y de Payment.objects.create
│   ├── storefront.py           # create_storefront_checkout, next_order_number, PAYMENT_START_FAILED
│   ├── webhooks.py             # reconcile_paid/failed/expired_session, reconcile_stripe_refund, reconcile_refunded_charge
│   ├── refunds.py              # único dueño de los reembolsos: refund_order, sync_stripe_refund, saldos
│   ├── fulfillment.py          # envío del pedido: update_order_fulfillment, FULFILLMENT_TRANSITIONS
│   └── admin.py                # pedidos del panel, link de pago y cobro del staff
├── views/
│   ├── __init__.py             # reexporta las views con __all__
│   ├── storefront.py           # POST /api/checkout/
│   ├── admin.py                # /api/admin/orders/** (incluye POST .../refunds/ y .../fulfillment/)
│   └── webhooks.py             # POST /api/webhooks/stripe/
├── migrations/
└── tests/
```

Ejemplo de una app con una sola superficie (el panel):

```text
apps/dashboard/
├── __init__.py
├── apps.py
├── urls.py
├── views.py                    # GET /api/admin/dashboard/ (sin views/: una sola superficie)
├── services/
│   ├── __init__.py             # reexporta get_dashboard_counts
│   └── counts.py
└── tests/
```

`apps/authentication/` (solo storefront: login, sesión y enlaces por correo) y `apps/authorization/` (solo panel) siguen la misma regla:

```text
apps/authentication/            # quién es cada uno
├── apps.py
├── urls.py
├── views.py                    # login, logout, sesión, reset, reenvío de verificación
├── models/
│   ├── __init__.py             # reexporta User, AccountToken, split_full_name, compose_display_name
│   ├── account_token.py
│   └── user.py
├── services/
│   ├── __init__.py             # reexporta la API pública con __all__
│   ├── credentials.py
│   ├── email_verification.py
│   ├── login.py
│   ├── password_reset.py
│   └── tokens.py
├── utils/
│   ├── background.py
│   └── throttling.py
├── docs/                       # schemas.py, examples.py, extensions.py
├── migrations/
└── tests/

apps/authorization/             # quién puede qué; solo la consume el panel
├── admin.py                    # Role y User en /admin/ (única app con admin.py)
├── apps.py
├── urls.py
├── views.py                    # /api/admin/users/**, /api/admin/roles/
├── models/
│   ├── __init__.py             # reexporta Role, ADMIN_ROLE_SLUG, EMPLOYEE_ROLE_SLUG
│   └── role.py
├── permissions/
│   ├── __init__.py             # reexporta con __all__: las apps importan de apps.authorization.permissions
│   ├── catalog.py              # STAFF_PERMISSIONS, DEFAULT_EMPLOYEE_PERMISSIONS, resolve_staff_permission
│   └── classes.py              # clase DRF HasRolePermission, has_role_permission, is_staff_user
├── services/
│   ├── __init__.py             # reexporta la API pública con __all__
│   ├── grants.py               # grant_role, NO_ROLE, COMMAND_ACTOR
│   ├── roles.py                # helpers de Role, list_admin_roles y reglas contra escalar privilegios
│   └── users.py                # list/update/delete_admin_user, bloqueo y último admin
├── management/commands/grant_role.py
├── docs/
├── migrations/
└── tests/
```

## Layout de cada app

| App | Raíz | Carpetas de código |
|---|---|---|
| `audit` | `views.py` (panel) | `models/activity_log.py`; `services/recording.py` (`record_activity`), `services/listing.py` (`list_activity_page`, `PAYMENT_ID_KEYS`) |
| `authentication` | `views.py` (storefront) | `models/`, `services/`, `utils/`, `docs/` |
| `authorization` | `admin.py`, `views.py` (panel) | `models/`, `permissions/`, `services/`, `management/commands/`, `docs/` |
| `cart` | — | `models/cart.py`; `services/storefront.py` (`get_cart`, `replace_cart`, `merge_session_cart`, `current_cart_id`, `CART_SESSION_KEY`), `services/admin.py` (listado, estado, contadores y purga); `views/storefront.py`, `views/admin.py`; `docs/`; `management/commands/purge_carts.py`; `apps.py` conecta `user_logged_in` |
| `catalog` | — | `models/product.py`, `models/application.py`; `serializers/storefront.py`; `services/admin.py`, `services/pricing.py` (`price_lines`, `build_totals`, `serialize_totals`); `views/storefront.py`, `views/admin.py`; `management/commands/import_catalog.py`; `data/` |
| `checkout` | — | `models/order.py`, `models/payment.py`, `models/refund.py`; `services/payments.py`, `services/storefront.py`, `services/webhooks.py`, `services/refunds.py`, `services/fulfillment.py` (envío, guía y correo "has shipped"), `services/admin.py`; `views/storefront.py`, `views/admin.py`, `views/webhooks.py`; `docs/` (solo `POST /api/admin/orders/<id>/refunds/` y `.../fulfillment/`) |
| `customers` | — | `models/customer.py`; `services/storefront.py` (perfil de la sesión, invitados, alta, verificación, activación y cuenta), `services/admin.py`; `views/storefront.py`, `views/admin.py` |
| `dashboard` | `views.py` (panel) | `services/counts.py` |
| `fitment` | `views.py` (storefront) | `services/compatibility.py` |
| `integrations` | `exceptions.py` (excepción documentada) | un paquete por capacidad con un módulo por proveedor |
| `numbering` | — (sin endpoints ni `urls.py`) | `models/document_sequence.py`, `services/document_numbers.py` |
| `quotes` | — | `models/quote.py`; `services/lifecycle.py`, `services/rendering.py`, `services/storefront.py`, `services/admin.py`, `services/pdf.py`, `services/tax.py` (impuesto que calcula el servidor al guardar desde el panel, dirección de envío y override); `views/storefront.py`, `views/admin.py`, `views/pdf.py`; `templates/quotes/`; `management/commands/expire_quotes.py` |
| `shipping` | `views.py` (storefront) | `services/rates.py` |
| `tax` | `views.py` (storefront) | `services/sales_tax.py` |
| `vin` | `views.py` (storefront) | `services/decoding.py` |
| `health` | `views.py` (plataforma: `GET /api/health/`) | `services/database.py` (`database_is_available`), `docs/` |

Apps sin tabla y por lo tanto sin `models/` ni `migrations/`: `fitment`, `shipping`, `tax`, `vin`, `dashboard`, `integrations`, `health`.

### Cómo se parte `services/`

`services/` siempre es un paquete, aunque tenga un solo módulo, y `services/__init__.py` reexporta la API pública con `__all__`, así `from apps.<app>.services import ...` no depende de la división. Reglas:

- En una app con superficie pública y de panel, lo público va en `services/storefront.py` y lo del panel en `services/admin.py`. Si alguno pasa de ~400 líneas o mezcla temas, se parte además por tema con nombres claros: `checkout` separa `payments.py` (Stripe) y `webhooks.py` (conciliación) del checkout del storefront; `quotes` separa `lifecycle.py` (número, token y vencimiento), `rendering.py` (serialización, enlaces y HTML) y `pdf.py` (WeasyPrint), que usan las dos superficies.
- En una app con una sola superficie, un módulo por tema, nombrado por el tema (`rates.py`, `counts.py`, `login.py`), sin módulos de una sola función ni cajones de sastre. Nunca `common.py` o `helpers.py` dentro del paquete: un helper que comparten dos módulos vive en el módulo dueño de su tema y los demás lo importan de ahí.
- Sin imports circulares entre los módulos del paquete: las dependencias van en una sola dirección y ninguno importa del `__init__`; se importan por el módulo concreto (`from apps.checkout.services.payments import start_stripe_payment`). Las otras apps importan del paquete (`from apps.checkout.services import start_stripe_payment`) o del módulo concreto.
- Los tests parchean el módulo donde se USA la función, no el `__init__` que la reexporta: cada módulo tiene su propia referencia, así que parchear el reexport no cambia lo que llama el código. El logger de cada módulo es `logging.getLogger(__name__)`, así que `caplog` apunta al módulo concreto (`apps.checkout.services.payments`).

`apps/authentication/services/` es el ejemplo:

| Módulo | Contenido | Importa del paquete |
|---|---|---|
| `tokens.py` | Emitir, bloquear e invalidar `AccountToken` (TTL, `issue_account_token`, `issue_activation_token`, `invited_emails`, `lock_activation_token`, `lock_account_token`, `invalidate_password_reset_tokens`) y `send_account_email` (entrega fuera del request con `run_in_background`) | nada |
| `credentials.py` | `parse_email`, `password_error`, `change_password`, `create_account` (hashea antes de mirar si el email existe), `EMAIL_ALREADY_EXISTS` | `tokens` |
| `login.py` | `authenticate_user`, `serialize_session_user`, `csrf_token_payload` | nada |
| `password_reset.py` | `request_password_reset`, `confirm_password_reset` | `credentials`, `tokens` |
| `email_verification.py` | `send_verification_email`, `send_existing_account_email` (aviso del registro con un email ya registrado, sin token), `resend_verification_email`, `consume_email_verification` | `tokens` |

`apps/authorization/services/` sigue las mismas reglas:

| Módulo | Contenido | Importa del paquete |
|---|---|---|
| `roles.py` | Helpers de Role (`is_full_access`, `permission_codenames_for_role`, `role_permission_pairs`, `role_grants_within`, `serialize_role`, `role_by_slug`), `list_admin_roles` y las reglas contra escalar privilegios (`has_full_access_role`, `update_privilege_error`). Importa el catálogo e `is_staff_user` de `permissions/`, nunca al revés | nada |
| `users.py` | `list_admin_users`, `update_admin_user`, `delete_admin_user` y lo que comparte con `grants.py`: `lock_accounts`, `fresh_user`, `is_last_full_access_user`, `log_user_activity`, `LAST_FULL_ACCESS` | `roles` |
| `grants.py` | `grant_role`, `NO_ROLE`, `COMMAND_ACTOR` (`manage.py grant_role`) | `roles`, `users` |

`apps/common/` no es una app de Django: es un paquete de helpers sin estado (ver más abajo) y no lleva `apps.py`, `urls.py` ni entrada en `INSTALLED_APPS`.

`apps/authentication/` (label `authentication`) es quién es cada uno: login, logout, sesión, throttle, los modelos `User` y `AccountToken` con sus migraciones y los enlaces por correo (`AccountToken`: `/api/password-reset/`, `/api/password-reset/confirm/`, `/api/verify-email/resend/`, y los servicios `consume_email_verification`, `issue_activation_token` y `lock_activation_token` que usa `customers`). No importa `apps.customers`: `/api/register/`, `/api/verify-email/` y `/api/activate/` son views de `apps/customers/` porque crean o vinculan el perfil `Customer`. `create_account` siempre crea la cuenta sin Role. Los correos salen por `send_email` del adaptador `apps/integrations/email/resend.py`; los de cuenta, fuera del request con `run_in_background` (`apps/authentication/utils/background.py`), para que el tiempo de respuesta no revele qué correos tienen cuenta. La etiqueta Django sale del nombre del paquete; no se llama `auth` porque esa etiqueta ya es de `django.contrib.auth`. `User` es el `AUTH_USER_MODEL` (`authentication.User`) y la auth es la estándar de Django: el login es el `ModelBackend` por defecto; los permisos salen de `User.has_perm`, que lee solo el Role. No hay backend propio, `authenticate()`/`login()`/`logout()` en las views y `SessionAuthentication` de DRF. La sesión es la de Django (`django_session`, cookie `sessionid`; en producción `__Host-sessionid`) y no guarda nada propio del login: `csrf_token_payload` está en `apps/authentication/services/login.py` y `CART_SESSION_KEY` en `apps/cart/services/storefront.py`, porque el carrito es dueño de su clave de sesión. `UserManager.create_superuser` (`createsuperuser`, para desarrollo) asigna el Role `admin` importándolo de `apps.authorization.models`. Importar `services` desde las otras apps; nunca duplicarlos ni reimplementar sesiones o autenticación.

`apps/authorization/` (label `authorization`) es quién puede qué: el modelo `Role` (`models/role.py`, tabla `roles`, M2M a `Permission`) y sus migraciones (`0001_initial` y `0002_seed_roles`, que siembra los permisos del panel, el Role `admin` de acceso total y `employee` con `DEFAULT_EMPLOYEE_PERMISSIONS`), `permissions/` (`catalog.py` con el catálogo y `classes.py` con la clase DRF `HasRolePermission`: `STAFF_PERMISSIONS`, `DEFAULT_EMPLOYEE_PERMISSIONS`, `CODE_TO_PERMISSION`, `PERMISSION_TO_CODE`, `resolve_staff_permission`, `ALL_PERMISSION_CODENAMES`, `is_staff_user` y `has_role_permission`), `views.py` y `services/` (`users.py`, `roles.py` con los helpers de Role como `role_grants_within` y `serialize_role`, y `grants.py`: `GET /api/admin/users/`, `PUT`/`DELETE /api/admin/users/<id>/` y `GET /api/admin/roles/`, con `users.manage`), `admin.py` (el registro de `User` y `Role` en `/django-admin/`), `management/commands/grant_role.py` y su `docs/`. **Nadie crea cuentas desde el panel; se asigna Role a cuentas registradas**: no hay `POST /api/admin/users/`, el `PUT` solo acepta `role` y `active` (otro campo es 400) y el primer admin sale de registrarse en la tienda (o `createsuperuser` en desarrollo) y `python manage.py grant_role --email ... --role admin` (`--role none` quita el Role). La dependencia va en un solo sentido, `authorization` ← `authentication`: `User.role` apunta a `authorization.Role` y el login usa `is_staff_user` de `apps.authorization.permissions` y `serialize_role`/`permission_codenames_for_role` de `apps.authorization.services`; `authorization` nunca importa `authentication`, llega al `User` con `get_user_model()` y la relación inversa `role.users`. Por eso los errores genéricos del esquema (`ErrorResponseSerializer`, `OkResponseSerializer`) y `RoleSummarySerializer` viven en `apps/authorization/docs/` y `apps/authentication/docs/` los importa de ahí.

## Documentación OpenAPI: `apps/<app>/docs/`

drf-spectacular publica el esquema en `/api/schema/` (Swagger en `/api/docs/`, ReDoc en `/api/redoc/`, solo para staff). La documentación de una app vive entera en `apps/<app>/docs/`; las views no llevan `@extend_schema` ni `serializer_class` para documentar.

| Archivo | Contenido |
|---|---|
| `docs/__init__.py` | Docstring del paquete |
| `docs/schemas.py` | Serializers de DRF que solo describen bodies de request y response, más `{"error": str}` (`ErrorResponseSerializer` de `apps/authorization/docs/schemas.py`, también para los errores de DRF: CSRF, throttle, JSON mal formado, 415). Ninguna view los usa en runtime. Sin docstrings en las clases: drf-spectacular los publica como descripción; el porqué va en un comentario `#` |
| `docs/examples.py` | `OpenApiExample` con los mensajes de error literales del código |
| `docs/extensions.py` | Una `OpenApiViewExtension` por view, con `target_class` como string con la ruta del módulo concreto de la view (`"apps.<app>.views.<View>"` en una app con `views.py`, `"apps.<app>.views.<superficie>.<View>"` en una con `views/`) y `view_replacement()` que devuelve una subclase decorada con `@extend_schema` (o `@extend_schema_view` si la view tiene varios métodos) |

`AppConfig.ready()` importa `apps.<app>.docs.extensions` para registrarlas; es la única línea fuera de `docs/`. La subclase existe solo mientras se genera el esquema, así que documentar nunca cambia cómo responde la view.

Reglas de contenido: `summary`, `description` y ejemplos en inglés (los lee quien consume la API); `description` con permiso, throttle y efectos (correos, sesiones revocadas, tokens invalidados, bitácora); `tags` por superficie (`auth`, `admin: users`); `operation_id` explícito para evitar colisiones; un `OpenApiResponse` por código que la view o DRF devuelven de verdad. Todo error se documenta con `ErrorResponseSerializer` (`{"error": str}`): `config/exceptions.py` convierte los de DRF a la misma forma, así que no hay `detail` ni esquemas polimórficos de error. Los ejemplos de los errores de DRF (`MALFORMED_JSON`, `CSRF_FAILED`, `UNSUPPORTED_MEDIA_TYPE`, `THROTTLED`) son `error_example` con el mensaje literal de DRF.

La autenticación es `SessionAuthentication` de DRF, que drf-spectacular ya describe (`cookieAuth`): no hace falta una `OpenApiAuthenticationExtension` propia. Los tests del esquema van en `apps/<app>/tests/test_api_schema.py` y assertean que generar el esquema no emite advertencias ni errores para las views de la app (`GENERATOR_STATS` de `drf_spectacular.drainage`).

## Paquetes compartidos: `apps/common` y `apps/numbering`

| Módulo | Funciones | Por qué vive aquí |
|---|---|---|
| `common/ids.py` | `random_id(prefix)` | Todos los ids de dominio (`OID…`, `C…`, `U…`, `PAY…`) tienen el mismo formato |
| `common/numbers.py` | `to_number(value, default=0.0)`, `money(value)`, `money_decimal(value)`, `to_cents(value)` | Única coerción numérica, único redondeo de dinero (`ROUND_HALF_UP` a centavos; un `Decimal` se redondea sin pasar por `float`) y única conversión a centavos enteros para Stripe |
| `common/tokens.py` | `hash_token(token)` | SHA-256 de los tokens de enlace (`AccountToken`) |
| `common/links.py` | `app_url(path)` | URL absoluta del SPA sin doble slash, con el respaldo de desarrollo en un solo lugar |
| `numbering/services/document_numbers.py` | `next_document_number(key, prefix)` | La numeración la usan pedidos y cotizaciones, así que no es de `checkout`; tiene modelo, y `common` por diseño no tiene |

`to_number` trata `None`, `False`, `""`, `0` y lo no numérico como "sin dato" y devuelve `default`. Un `"0"` escrito como texto sí es `0.0`; quien necesita un mínimo lo aplica (`max(1, int(to_number(qty, 1)))`, `to_number(qty, 1.0) or 1.0`).

`DocumentSequence` (tabla `document_sequences`) pasó de `checkout` a `numbering` con migraciones solo de estado (`checkout/0004_move_document_sequence` y `numbering/0001_initial` con `SeparateDatabaseAndState`): la tabla y sus filas no se tocan.

## Precio de líneas y totales: `apps/catalog/services/pricing.py`

El repreciado y los totales salen solo de aquí. Vive en `catalog` porque el catálogo es dueño del precio y está por debajo de `checkout` y `quotes`; `build_totals` no va en `apps/common/numbers.py` porque la forma de los totales (con el core charge) es del dominio y `common` no tiene dominio.

| Función / clase | Qué hace |
|---|---|
| `price_lines(raw_items, *, allow_custom_price=False, max_quantity=MAX_STOREFRONT_QUANTITY)` | Valida cada línea (objeto, cantidad entera de 1 a `max_quantity`; ausente es 1), toma el precio y el core del catálogo (productos activos; los demás se descartan) o, con `allow_custom_price`, de la línea (`unitPrice` o el `price` heredado, 0 o más, sin leer el catálogo). Redondea el precio unitario a centavos antes de multiplicar. Devuelve `PricedLines(lines, subtotal, core)` en `Decimal` |
| `parse_quantity(value, *, max_quantity)` | La regla de cantidad, sola |
| `InvalidQuantity`, `InvalidPrice`, `UnpricedProducts(lines)` | Rechazos (base `PricingError`): cantidad fuera de rango o línea que no es objeto; precio propio negativo o no numérico; producto del catálogo sin precio positivo |
| `build_totals(subtotal, core, shipping=0, tax=0, discount=0)` | `subtotal`, `core`, `shipping`, `tax` y `total` en `Decimal`, cada uno con `money_decimal`; `discount` solo aparece si no es cero |
| `serialize_totals(totals)` | Los mismos totales como `float` para el JSON (`Order.data`, `Quote.data`, respuestas) |

Quién la usa y cómo traduce los rechazos:

| Caller | Parámetros | `InvalidQuantity` | Otros |
|---|---|---|---|
| `create_storefront_checkout` (`checkout/services/storefront.py`) | por defecto | 400 `Item quantity must be a whole number from 1 to 99` | `UnpricedProducts` → 409 `These items have no valid price and cannot be purchased online: ...` |
| `create_quote_from_request` (`quotes/services/storefront.py`) | por defecto | 400, mismo mensaje | `UnpricedProducts` → 409 `... cannot be quoted online: ...` |
| `upsert_admin_quote` (`quotes/services/admin.py`) | `allow_custom_price=True, max_quantity=None` | 400 `Item quantity must be a whole number of at least 1` | `InvalidPrice` → 400 `Item prices must be amounts of 0 or more`; guarda las líneas normalizadas y el impuesto que recalcula `resolve_quote_tax` sobre el subtotal y el core repreciados |
| `_quote_line` (`quotes/services/rendering.py`) y `_create_checkout_session` (`checkout/services/payments.py`) | `allow_custom_price=True, max_quantity=None` sobre líneas ya guardadas | la presentación muestra la línea sin total | Stripe cobra `to_cents` de cada línea: la suma es exactamente el `Payment.amount` |

El impuesto (`apps/tax/services/sales_tax.py`) también es `Decimal`: `FALLBACK_TAX_RATES` son `Decimal("0.06")` y `calculate_sales_tax` devuelve `tax` y `rate` en `Decimal`; `estimate_tax_for_customer` (y `estimate_tax`, que le pasa el perfil de la sesión) los serializa para el JSON y el adaptador de TaxJar convierte a `float` solo el body del request.

## Fronteras entre apps

`tests/test_app_boundaries.py` arma el grafo de imports de `apps/*` con `ast` (incluye los imports dentro de funciones; excluye `tests/` y `migrations/`) y falla si:

- hay un ciclo entre dos o más apps;
- `common` o `numbering` importan otra app;
- `common` tiene modelos, migraciones o views;
- alguien importa `customer_for_user`, `resolve_guest_customer` o `link_guest_history` desde otro módulo que no sea `apps.customers.services`.
- `authorization` importa `authentication`.

La permission class de `apps.authorization` y los throttles de `apps.authentication` no cuentan como arista: todas las views los usan como usarían DRF, y el test verifica que esos módulos no importan otras apps. Para no cerrar un ciclo, `customers` llega a pedidos y cotizaciones por las relaciones inversas (`customer.orders`, `customer.quotes`) en lugar de importar `Order` o `Quote`.

## Apps transversales: `audit` y `dashboard`

`apps/audit/` es la bitácora transversal (`ActivityLog`, tabla `activity_logs`, permiso `activity.view` y `GET /api/admin/activity/`). Su única API pública es `record_activity` (`apps/audit/services/recording.py`, reexportado en `apps.audit.services`):

```python
from apps.audit.services import record_activity

record_activity(actor_email, "ORDER_STATUS_CHANGED", entity_type="ORDER", entity_id=order.pk, data={"status": status})
```

`actor` es el email del staff o un actor de sistema (`"stripe"`), no una FK. Ninguna app fuera de `audit` importa `ActivityLog`; los tests de otras apps assertean la bitácora con `activity_count(**filters)` de `tests/factories.py`. `audit` no importa apps de dominio, así cualquier app puede registrar actividad sin crear ciclos. La respuesta de `/api/admin/activity/` es `{items, nextCursor}`, con las filas en camelCase (`actorId`, `entityType`, `entityId`, `createdAt`) de la más nueva a la más vieja; pagina con `?limit=` (50 por defecto, tope 250) y `?before=<nextCursor>`, un cursor por `(created_at, id)`. `list_activity_page(limit, before, can_view_payment_ids=...)` quita de `data`, a cualquier profundidad, las claves de `PAYMENT_ID_KEYS` (`sessionId`, `paymentIntent`) salvo que la view le pase `True`; la view lo resuelve con `has_role_permission(user, "payments.transaction_id")`, así `audit` sigue sin conocer los dominios.

`apps/dashboard/` es agregación de solo lectura (`get_dashboard_counts` en `services/counts.py`, `GET /api/admin/dashboard/` con `dashboard.view`). No tiene modelos ni migraciones: lee `Order`, `Payment`, `Refund`, `Quote` y `Cart` de sus apps dueñas. `salesToday` sale de `net_sales_between(start, end)`: subtotal + core + envío de `order.data.totals` por cada pago cobrado en el período (`Payment.paid_at`), menos los `Refund` `SUCCEEDED` creados en el período; la regla completa está en su docstring. Como no hay modelo propio, su permiso cuelga de `authorization.Role` (`view_dashboard`), el modelo que ya gobierna el acceso al panel de staff.

## Adaptadores de proveedores: `apps/integrations`

Un módulo por proveedor, agrupado por capacidad:

| Adaptador | Funciones públicas | Lo usa |
|---|---|---|
| `email/resend.py` | `is_configured()`, `send_email(to, subject, html, attachments=None, reply_to=None)` | `authentication`, `checkout`, `quotes` |
| `payments/stripe.py` | `is_configured()`, `create_checkout_session(...)`, `expire_checkout_session(id)`, `retrieve_payment_method(id)`, `create_refund(payment_intent, amount_cents, idempotency_key, metadata)`, `construct_webhook_event(payload, signature)` | `checkout`, `quotes` |
| `shipping/easypost.py` | `is_configured()`, `get_rates(to_address, from_address, parcel)` | `shipping` |
| `tax/taxjar.py` | `is_configured()`, `calculate_tax(from_zip, to_state, to_zip, to_city, to_street, amount, shipping)` | `tax` |
| `vehicles/nhtsa.py` | `decode_vin(vin)` | `vin` |

Contrato de un adaptador:

- Lee su key o secreto de `settings` y lanza `ProviderNotConfigured` si falta. La excepción es `resend.send_email`, que devuelve `{"sent": bool, "id" | "reason"}`: el correo es un efecto secundario que nunca corta la operación.
- Mapea la respuesta a dicts planos (sin objetos del SDK) y envuelve los errores de red, HTTP y JSON en `ProviderError` (`ProviderUnavailable` para un estado HTTP de error cuando el dominio lo distingue).
- No importa modelos ni apps de dominio y no decide reglas de negocio.

El dominio traduce: `apps/tax/services/sales_tax.py` cae a `FALLBACK_TAX_RATES` ante cualquier `ProviderError`; `apps/shipping/services/rates.py` registra el mensaje de EasyPost en el log y responde 502 con un mensaje genérico; `apps/vin/services/decoding.py` elige el mensaje de error; `apps/checkout/services/payments.py` arma líneas, URLs y metadata de la Checkout Session y devuelve `None` si no puede leer la tarjeta. Igual que en shipping, el texto de Stripe va al log: el checkout del storefront y el de cotizaciones responden 502 con `PAYMENT_START_FAILED` ("Payment could not be started. Please try again.") y el link de pago, el cobro y el reembolso del panel con `STRIPE_REQUEST_FAILED` ("Stripe request failed; see server logs.", definido en `apps/checkout/services/payments.py`). Un proveedor nuevo es un módulo nuevo aquí, sus tests en `apps/integrations/tests/` y su paquete en `PROVIDER_PACKAGES` de `tests/test_integrations_boundary.py`.

## Migraciones

El ORM es dueño de todas las tablas. Para una tabla nueva o un cambio de columna: editar el modelo, correr `python manage.py makemigrations <app>` y revisar el archivo generado. Un default que también tiene que valer para un `INSERT` fuera del ORM va con `db_default` (por ejemplo `db_default=Now()` junto a `default=timezone.now`).

Las migraciones `0003_managed_*` (y `cart/0002_managed_cart`) convirtieron las antiguas tablas creadas a mano con SQL. El proyecto no estaba en producción, así que cada una descarta la tabla heredada y la crea desde el modelo:

```python
operations = [
    migrations.SeparateDatabaseAndState(
        state_operations=[migrations.DeleteModel(name="Cart")],
        database_operations=[
            migrations.RunSQL(
                "DROP TABLE IF EXISTS carts CASCADE",
                reverse_sql=migrations.RunSQL.noop,
            ),
        ],
    ),
    migrations.CreateModel(name="Cart", fields=[...], options={"db_table": "carts"}),
]
```

El `DeleteModel` de estado no borra el `ContentType`, así que los permisos del modelo y los Roles que los tienen sobreviven. No repetir este patrón en cambios nuevos: con datos reales, un cambio de esquema es un `AddField` o `AlterField` normal.

`tests/test_migrations.py` prueba que no queda ningún modelo sin administrar, que `migrate` crea cada tabla de dominio y que `makemigrations --check` no detecta cambios.

## Formas de retorno de los services

Preferir la tupla `(data, status)`, que deja la view mecánica:

```python
# apps/shipping/services/rates.py
def get_shipping_rates(payload: dict) -> tuple[dict, int]:
    if not parcel:
        return {"error": "Parcel information required"}, 400
    return {"configured": True, ...}, 200
```

`apps/authorization/services/` (`users.py` y `roles.py`) usa una forma más vieja que devuelve `{"error": ..., "status": ...}` dentro del dict del resultado. No tocarla, pero no propagarla a código nuevo.

La view nunca desarma el resultado a mano: `service_response(result, success_status=...)` de `config/responses.py` traduce los dos contratos (tupla, o dict con `error`/`status`) a `Response`. Un dict de error pierde toda clave que no sea `error`.

Los services devuelven `None` en lugar de lanzar excepción cuando "no encontrado" es un resultado esperado que la view tiene que traducir. Por ejemplo `authenticate_user()` (que llama a `django.contrib.auth.authenticate()`) devuelve `None` tanto para usuario inexistente como para password incorrecto o cuenta inactiva, así la view responde un único 401 genérico.

## Cableado de las views

Toda view declara `permission_classes` (el default de settings es `HasRolePermission`, solo staff, y solo existe para que un olvido quede cerrado; `tests/test_view_permissions.py` exige la declaración). Las admin views declaran el permiso que exigen y no contienen reglas; la autenticación es la default (`SessionAuthentication`) y no se repite:

```python
class AdminProductDetailView(APIView):
    permission_classes = [HasRolePermission]
    required_permission = "products.edit"
```

`HasRolePermission` traduce `required_permission` con `resolve_staff_permission` y pregunta `request.user.has_perm("app_label.codename")`; colapsa "sin sesión" y "sin permiso" en un solo 403 `{"error": "You do not have permission to perform this action."}`. Las views de gestión de usuarios, la de sesión, la cuenta del cliente, el `PATCH`/`DELETE` de pedidos y la exención de impuestos del panel en cambio separan el 401 del 403 para que el SPA distinga "sesión vencida" (redirige a `/login`) de "sin permiso": declaran `permission_classes = [AllowAny]` con un comentario y chequean a mano.

## Reembolsos de Stripe: `apps/checkout/services/refunds.py`

`Refund` (`models/refund.py`, tabla `refunds`) pertenece a un `Payment` (FK `CASCADE`, llevada a Postgres por `checkout/0007_refund_db_on_delete`): `amount` (`Decimal`, 2 decimales), `status` (`RefundStatus`: `PENDING`, `SUCCEEDED`, `FAILED`, `CANCELED`), `reason`, `stripe_refund_id` (único, vacío hasta que Stripe responde), `created_by` (email del staff o `"stripe"`) y `data`. `tests/test_stripe_payment_boundary.py` falla si alguien fuera de `services/refunds.py` llama a `create_refund` o hace `Refund.objects.create`.

Estados de cobro: `order.payment_status` (`OrderPaymentStatus`) y `Payment.status` (`PaymentStatus`) usan `PAID`, `PARTIALLY_REFUNDED` y `REFUNDED` (`CHARGED_PAYMENT_STATUSES` de `services/payments.py`). Los tres cuentan como "ya cobrado": el webhook no vuelve a marcar PAID un pago reembolsado, el link de pago y el cobro del panel responden 409 y una cotización con un pedido reembolsado no se vuelve a pagar. Solo cuenta lo reembolsado con `SUCCEEDED`; `order.status` no cambia al reembolsar.

Flujo de `POST /api/admin/orders/<id>/refunds/` (`payments.refund`, `refund_order`):

1. Primera transacción: bloquea pedido y pagos (mismo orden que el webhook, `lock_order_and_payment`), exige `payment_status` `PAID` o `PARTIALLY_REFUNDED` y un pago con `payment_intent`, valida el monto contra el saldo (cobrado − `PENDING` − `SUCCEEDED`; sin `amount`, el saldo entero) y confirma la fila `Refund` `PENDING`.
2. Fuera de la transacción llama a `create_refund` con el id de la fila como `idempotency_key` y `metadata.refund_id`. Un `ProviderError` marca la fila `FAILED` (devuelve el saldo), va al log, registra `REFUND_FAILED` y responde 502 `STRIPE_REQUEST_FAILED`.
3. Segunda transacción: guarda `stripe_refund_id` y el estado que devolvió Stripe, recalcula `Payment.status`/`order.payment_status` (`apply_refund_totals`) y registra `REFUND_CREATED`.

`checkout.session.expired` (`reconcile_expired_session`): el `Payment` PENDING de esa sesión pasa a `CANCELLED` (`cancelReason: SESSION_EXPIRED`) sin llamar a Stripe y, si el pedido sigue `PENDING_PAYMENT`, sin cobrar y sin otra sesión pendiente, `cancel_unpaid_order(order, "PAYMENT_EXPIRED")` y bitácora `ORDER_EXPIRED`. Un pedido pagado, del panel (`OPEN`) o con un link más nuevo no se toca; idempotente, mismo bloqueo pedido → pago, siempre 200. Una cotización con ese pedido vuelve a pagarse porque `checkout_from_quote` ignora los `CANCELLED`. `checkout.session.completed` guarda `Payment.paid_at`.

Webhook (`services/webhooks.py` → `sync_stripe_refund`): `refund.created`, `refund.updated` y `refund.failed` crean o actualizan la fila, idempotente por `stripe_refund_id`; una fila nuestra que todavía no guardó su id se reconoce por `metadata.refund_id`; un reembolso del dashboard crea la fila con `created_by="stripe"`. Un `pending` atrasado no pisa un estado final informado por Stripe. `charge.refunded` solo sincroniza si el cargo trae la lista `refunds` (desde la API 2022-11-15 no viene). Siempre 200. La bitácora oculta `stripeRefundId` sin `payments.transaction_id` (`PAYMENT_ID_KEYS`).
