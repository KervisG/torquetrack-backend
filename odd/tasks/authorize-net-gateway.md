# Authorize.net payment gateway

Objetivo: reemplazar Stripe por completo por Authorize.net (Accept Hosted) en backend y frontend.
Rama: `feat/authorize-net` en `torquetrack-backend` y `torquetrack-frontend`. Entrega: ask-on-risk. Runner: `python -m pytest` (backend), `npm test` (frontend).

## Specs

- S1. "quiero agregar la pasarela de pago ycambira a Authorize.net ya tengo mi key generada" — el cobro de checkout, cotización pública, link de pago del panel y "take payment" se hace con Authorize.net.
- S2. "se elimina el stripe completo" — no queda código, dependencia (`stripe` en requirements), setting, ruta de webhook ni texto de UI de Stripe.
- S3. Integración elegida por el usuario: "Accept Hosted (Recommended)" — el formulario de tarjeta lo muestra Authorize.net; el backend nunca ve datos de tarjeta.
- S4. Credenciales elegidas por el usuario: "Sandbox" — settings `AUTHORIZE_NET_API_LOGIN_ID`, `AUTHORIZE_NET_TRANSACTION_KEY`, `AUTHORIZE_NET_SIGNATURE_KEY`, `AUTHORIZE_NET_ENVIRONMENT` (`sandbox` por defecto, `production`).
- S5. (Supuesto técnico) El token de Accept Hosted vence a los 15 min: el `url` que se devuelve o se envía por correo apunta a un puente propio que genera el token al abrirse y hace el POST a Authorize.net.
- S6. (Supuesto técnico) El webhook firmado (`X-ANET-Signature`, HMAC-SHA512 con la Signature Key) concilia cobros, reembolsos, anulaciones y avisos de fraude, releyendo la transacción con `getTransactionDetails` antes de marcar nada.
- S7. (Supuesto técnico) Reembolso del panel: transacción sin liquidar → `voidTransaction` (solo total); liquidada → `refundTransaction` (total o parcial).
- S8. (Supuesto técnico) Sin evento de "sesión expirada": una tarea de Celery cancela los pagos PENDING viejos con la misma regla que tenía `checkout.session.expired`.
- S9. (Supuesto técnico) Authorize.net no avisa contracargos por webhook: se elimina el flujo de disputas de Stripe.

## Tasks

| ID | Specs | Ruta | Estado | Commit |
|----|-------|------|--------|--------|
| T1 | S2,S4,S6 | inline | hecho | backend e609648 |
| T2 | S1,S3,S5 | inline | hecho | backend e609648 |
| T3 | S6,S9 | inline | hecho | backend e609648 |
| T4 | S7 | inline | hecho | backend e609648 |
| T5 | S8 | inline | hecho | backend e609648 |
| T6 | S2 | inline | hecho | backend e609648 |
| T7 | S2 (frontend) | inline | hecho | frontend 15a42e4 |
| T8 | S1,S6 | manual | pendiente | prueba real en sandbox |

- T1: adaptador `apps/integrations/payments/authorize_net.py` + settings + tests; borrar adaptador y SDK de Stripe.
- T2: `start_payment` + puente `GET /api/payments/<id>/pay/` + llamadores (storefront, cotización, panel).
- T3: webhook `/api/webhooks/authorize-net/` y conciliación.
- T4: reembolsos (void/refund) + migración `stripe_refund_id` → `provider_refund_id`.
- T5: tarea de Celery que vence pagos pendientes.
- T6: docs OpenAPI, bitácora, throttles, nginx, README.
- T7: frontend (tipos, etiquetas, políticas, handlers de test).

Ruta: todo inline (preferencia del usuario: sin subagentes; ningún disparador de writer aplica).

## Log

- L1 (2026-11-20): "quiero agregar la pasarela de pago ycambira a Authorize.net ya tengo mi key generada"
- L2 (2026-11-20): "se elimina el stripe completo elimina el stripe completo"; integración "Accept Hosted (Recommended)"; credenciales "Sandbox".
- L3: espejo Engram pendiente (proyecto ambiguo entre backend y frontend).
- L4 (2026-11-20): "tantos text no son necesarios recuerdas que ahora trabajmos con odd" — se borraron los tests de Stripe y quedó un test por regla (`test_authorize_net_flow.py`, `test_admin_refunds_views.py`).
- L5: verificación — backend 1724 passed, ruff limpio, `makemigrations --check` sin cambios; frontend 188 passed, tsc limpio.
- L6: siguiente paso: T8, cargar las credenciales en `.env`, registrar el webhook en el Merchant Interface y pagar una orden de prueba en sandbox.
