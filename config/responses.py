"""Traduce el resultado de un service al `Response` de DRF, en un solo lugar.

Los services no importan DRF y devuelven uno de dos contratos
(`skills/backend-architecture/references/app-layout.md`, "Formas de retorno"):

- la tupla `(data, status)`, que se responde tal cual;
- un dict: con `error` es `{"error": ...}` con su `status` (400 si falta), y
  sin `error` es el body de éxito.

Un error de un campo del input lleva además `field` (snake_case, ver
`apps/common/errors.py`); sin campo, el body no tiene la clave.

Vive en `config/` junto a `exceptions.py` por la misma razón: es cableado del
framework (arma un `Response`), no regla de ningún dominio, y `apps/common/`
no puede importar DRF.
"""
from rest_framework.response import Response


def service_response(result, *, success_status: int = 200) -> Response:
    if isinstance(result, tuple):
        data, status = result
        return Response(data, status=status)
    if "error" in result:
        # Solo el mensaje y el campo: `status` y cualquier otra clave del dict
        # de error son internos del service.
        body = {"error": result["error"]}
        if result.get("field"):
            body["field"] = result["field"]
        return Response(body, status=result.get("status", 400))
    return Response(result, status=success_status)
