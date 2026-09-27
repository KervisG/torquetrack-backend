"""`EXCEPTION_HANDLER` de DRF: un solo formato de error para toda la API.

Las views y los services responden `{"error": "<mensaje>"}`; los errores que
arma DRF por su cuenta (sin sesión, sin permiso, 404, 405, 415, throttle, JSON
mal formado, CSRF) salían como `{"detail": ...}` y el SPA solo lee `error`.
Este handler envuelve el de DRF y cambia solo el body: el código de estado,
los headers (`Retry-After`, `Allow`, `WWW-Authenticate`) y el rollback de la
transacción siguen siendo los de DRF.

Vive en `config/` y no en una app porque es cableado del framework que
referencia `settings`, igual que `urls.py`: no es regla de ningún dominio,
`apps/common/` no puede importar DRF y ponerlo en `authorization` mezclaría el
formato de los errores con quién puede qué.
"""
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        response.data = error_body(response.data)
    return response


def error_body(data) -> dict:
    """Un error de validación por campo conserva el detalle en `fields` y
    lleva el primer mensaje en `error`, para que el SPA siempre tenga una
    frase que mostrar."""
    if isinstance(data, dict):
        if "detail" in data:
            extra = {key: value for key, value in data.items() if key != "detail"}
            return {"error": _first_message(data["detail"]), **extra}
        return {"error": _first_message(data), "fields": data}
    return {"error": _first_message(data)}


def _first_message(value) -> str:
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list | tuple):
        for item in value:
            message = _first_message(item)
            if message:
                return message
        return ""
    return str(value)
