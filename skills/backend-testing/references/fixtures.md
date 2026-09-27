# Fixtures y entorno

## Cómo se arma la base de datos de test

No hay `conftest.py` propio ni `schema.sql`. pytest-django crea la base de test y aplica todas las migraciones, igual que `manage.py migrate`: cada tabla que lee un test la creó el ORM.

`tests/test_migrations.py` prueba que ningún modelo es `managed = False`, que `migrate` crea cada tabla de dominio (`DOMAIN_TABLES`), que no queda ninguna tabla retirada (`RETIRED_TABLES`: `sessions`, `employee_roles`) y que `makemigrations --check` no detecta cambios. `tests/test_audit_boundary.py` recorre los módulos con `ast` y falla si algo fuera de `apps/audit/` importa algo distinto de `record_activity`, o si `audit` importa una app de dominio. `tests/test_integrations_boundary.py` hace lo mismo con los proveedores: solo `apps/integrations/` importa `requests`, `stripe` y los SDKs, `integrations` no importa apps de dominio, `send_email` sale solo del adaptador y `calculate_sales_tax` solo del paquete `apps.tax.services` (o de su módulo `sales_tax`). `tests/test_app_boundaries.py` arma el grafo de imports entre apps y falla ante un ciclo, si `apps/common` o `apps/numbering` importan otra app, o si la resolución del cliente (`customer_for_user`, `resolve_guest_customer`, `link_guest_history`) se importa de otro lado que el paquete `apps.customers.services` (o uno de sus módulos).

## Helpers de arrange

Cuentas y perfiles salen de `tests/factories.py`, con el ORM:

```python
from tests.factories import create_customer, create_staff_user, create_user, session_client

create_staff_user("U_CASHIER", permissions=["payments.take"])  # Role propio con esos permisos
create_staff_user("U_OWNER", full_access=True)
customer = create_user("U_PAT", password="diesel-pass-123")      # sin Role: cliente
create_customer("C_PAT", email=customer.email, user=customer)
```

Sin `password` se guarda un hash inutilizable, porque PBKDF2 es lento; pasarlo solo en los tests que hacen login de verdad.

El resto de las tablas se arma con el ORM directo. Los campos JSON reciben el dict de Python, sin `json.dumps`:

```python
Product.objects.create(id="gm-65-injection-pump", data={"price": 189.99}, active=True)
Order.objects.create(id="ord_1", number="O10001", payment_status="PAID", data={"totals": {"total": 100.0}})
Cart.objects.create(id="cart_1", data={"items": [{"id": "p1", "qty": 1}]})
```

La bitácora se assertea sin importar el modelo:

```python
from tests.factories import activity_count

assert activity_count(action="ORDER_STATUS_CHANGED", entity_id="ord_1") >= 1
```

`created_at` y `updated_at` tienen `default=timezone.now`; pasarlos solo cuando el test depende de la fecha.

## Autenticar un request

```python
client, session_key = session_client("U_CASHIER")               # cookie `settings.SESSION_COOKIE_NAME`
client, _ = session_client("U_CASHIER", enforce_csrf=True)     # para probar CSRF
```

`POST /api/login/` existe, así que un test end-to-end puede loguearse de verdad. Seguir usando el helper para los tests que son sobre autorización y no sobre el login en sí: es más rápido y no consume la cuota del throttle.

## Falsear un proveedor

Los tests de dominio parchean la función del adaptador; `tests/test_integrations_boundary.py` además falla si un módulo fuera de `apps/integrations/` importa `requests` o un SDK.

```python
from tests.fakes import forbid_resend, install_resend

resend = install_resend(monkeypatch)            # resend.sent[0]["to"] == ["pat@example.com"]
forbid_resend(monkeypatch)                      # cualquier envío falla el test

monkeypatch.setattr(
    "apps.integrations.payments.stripe.create_checkout_session",
    lambda **kwargs: {"id": "cs_test_1", "url": "https://checkout.stripe.com/pay/cs_test_1"},
)
```

Un fallo del proveedor se simula lanzando `ProviderError` de `apps.integrations.exceptions`. Si el mensaje del proveedor no debe llegar al cliente, lanzarlo con un texto reconocible (`"... acct_internal_123"`), assertear el body genérico completo y buscar el texto en `caplog.text`. Sin key, el adaptador real ya responde "no configurado" sin tocar la red, así que un test de "sin proveedor" puede dejarlo sin parchear.

## Assertear que un proveedor NO se llama

```python
def _boom(**kwargs):
    raise AssertionError("TaxJar must not be called for an exempt customer")

monkeypatch.setattr("apps.integrations.tax.taxjar.calculate_tax", _boom)
```

El bypass por exención es una regla de corrección de dinero, así que probar la ausencia de la llamada importa tanto como probar el total devuelto.

## Fallos conocidos de entorno

El backend corre con Python 3.13 (`.python-version`). Con 3.14, Django 5.1 rompe el `Context` de templates (`'super' object has no attribute 'dicts'`); si aparece ese error, el `.venv` está en la versión equivocada: recrearlo con `uv venv --python 3.13 .venv`.

WeasyPrint necesita las librerías nativas de GTK/Pango, que `Dockerfile` instala solo para Linux. Sin ellas el import lanza `OSError` (no `ImportError`), así que los tests que renderizan el PDF llevan `@requires_weasyprint` de `apps/quotes/tests/pdf_support.py` y quedan `skipped` en Windows. Todo test nuevo que llame a `render_quote_pdf_bytes` (`apps/quotes/services/pdf.py`, directo o vía un endpoint) lleva el mismo marcador. Para correrlos, usar el contenedor.

## Base de datos local

`python -m pytest` necesita Postgres en `localhost:5435`. Levantarlo con `docker compose up -d db` desde la raíz del repo.
