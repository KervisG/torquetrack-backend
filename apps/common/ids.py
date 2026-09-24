import secrets


def random_id(prefix: str) -> str:
    """Mismo formato para todos los ids del dominio: prefijo + 12 hex."""
    return prefix + secrets.token_hex(6).upper()
