import hashlib


def hash_token(token: str) -> str:
    """Solo se guarda el SHA-256 de un token de enlace, nunca el valor en claro."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
