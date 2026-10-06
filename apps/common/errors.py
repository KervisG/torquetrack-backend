"""Body de un error de un service: `{"error": "<mensaje>"}` y, si el error es
de un campo del input, `field` con el nombre del campo en snake_case.

`field` es opcional y aditivo: `error` sigue siendo el mismo literal, así un
cliente que solo lee `error` no cambia. El SPA usa `field` para marcar el
input sin adivinarlo por el texto del mensaje. `config/responses.py` lo deja
pasar al body; cualquier otra clave del dict de error se descarta.
"""
from __future__ import annotations

import re

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def snake_case(name: str) -> str:
    """`partNumber` -> `part_number`; un nombre ya en snake_case no cambia."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def error_payload(message: str, field: str | None = None, *, status: int | None = None) -> dict:
    """Sin `status` es el body de la tupla `(data, status)`; con `status` es
    el dict de error que `service_response` traduce."""
    body = {"error": message}
    if field:
        body["field"] = snake_case(field)
    if status is not None:
        body["status"] = status
    return body
