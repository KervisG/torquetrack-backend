"""Documentación OpenAPI de `apps.roles`. Las views no llevan `@extend_schema`:
`extensions.py` las reemplaza al generar el esquema y `RolesConfig.ready()` la
registra. Los errores genéricos (`{"error"}`, `{"ok": true}`) y el resumen del
Role viven en `schemas.py`; las demás apps los importan de ahí."""
