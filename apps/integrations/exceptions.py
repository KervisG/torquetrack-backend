"""Excepciones tipadas que lanzan los adaptadores de `apps/integrations`.

Las apps de dominio las traducen a su respuesta (un 502, un 503, una tabla
de respaldo) sin conocer los errores propios de `requests` ni del SDK de
cada proveedor. `ProviderNotConfigured` hereda de `ProviderError` para que un
dominio que trata igual "sin key" y "proveedor caído" capture una sola clase.
"""


class ProviderError(Exception):
    """El proveedor no devolvió un resultado usable: red, HTTP o payload."""


class ProviderNotConfigured(ProviderError):
    """Falta la key o el secreto del proveedor en el entorno del servidor."""


class ProviderUnavailable(ProviderError):
    """El proveedor respondió con un estado HTTP de error."""


class WebhookSignatureError(ProviderError):
    """La firma o el payload de un webhook no pasó la verificación."""
