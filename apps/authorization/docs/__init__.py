"""Documentación OpenAPI de `apps.authorization`.

Las views no llevan `@extend_schema`: `extensions.py` las reemplaza solo al
generar el esquema. `AuthorizationConfig.ready()` importa ese módulo para
registrarlas.

Los errores genéricos (`{"error"}`, `{"detail"}` de DRF, `{"ok": true}`) y el
resumen del Role viven aquí y no en `apps.authentication.docs`: esta app está
debajo de `authentication`, que los importa de aquí. Así cada componente del
esquema tiene una sola clase y la dependencia sigue en un solo sentido.
"""
