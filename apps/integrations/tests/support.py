"""Respuesta HTTP falsa para los tests de los adaptadores que usan `requests`."""


class FakeResponse:
    def __init__(self, payload=None, ok=True, status_code=200, invalid_json=False):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code
        self._invalid_json = invalid_json

    def json(self):
        if self._invalid_json:
            raise ValueError("No JSON object could be decoded")
        return self._payload


class RecordingPost:
    """`requests.post` falso: guarda cada llamada y devuelve `response`."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return self.response
