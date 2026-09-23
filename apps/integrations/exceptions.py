"""`ProviderNotConfigured` hereda de `ProviderError` para que un dominio que
trata igual "sin key" y "proveedor caído" capture una sola clase."""


class ProviderError(Exception):
    """El proveedor no devolvió un resultado usable: red, HTTP o payload."""


class ProviderNotConfigured(ProviderError):
    """Falta la key o el secreto del proveedor en el entorno del servidor."""


class ProviderUnavailable(ProviderError):
    """El proveedor respondió con un estado HTTP de error."""


class WebhookSignatureError(ProviderError):
    """La firma o el payload de un webhook no pasó la verificación."""
