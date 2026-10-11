"""DigitalOcean Spaces (API compatible con S3) para las fotos de producto.

Cada objeto se sube como público: la tienda lo muestra por la URL del CDN sin
firmar nada. Cualquier fallo se reporta como `ProviderError`."""

from __future__ import annotations

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from apps.integrations.exceptions import ProviderError, ProviderNotConfigured

_SETTINGS = ("SPACES_BUCKET", "SPACES_REGION", "SPACES_KEY", "SPACES_SECRET")
# Un año: el nombre del objeto es único, así que su contenido nunca cambia.
CACHE_CONTROL = "public, max-age=31536000, immutable"


def is_configured() -> bool:
    return all(getattr(settings, name) for name in _SETTINGS)


def _client():
    missing = [name for name in _SETTINGS if not getattr(settings, name)]
    if missing:
        raise ProviderNotConfigured(f"{', '.join(missing)} not set")
    return boto3.client(
        "s3",
        region_name=settings.SPACES_REGION,
        endpoint_url=f"https://{settings.SPACES_REGION}.digitaloceanspaces.com",
        aws_access_key_id=settings.SPACES_KEY,
        aws_secret_access_key=settings.SPACES_SECRET,
        config=Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 2}),
    )


def public_url(key: str) -> str:
    base = settings.SPACES_PUBLIC_URL.rstrip("/") or (
        f"https://{settings.SPACES_BUCKET}.{settings.SPACES_REGION}.cdn.digitaloceanspaces.com"
    )
    return f"{base}/{key}"


def upload(*, key: str, content: bytes, content_type: str) -> str:
    """Sube el objeto y devuelve su URL pública."""
    client = _client()
    try:
        client.put_object(
            Bucket=settings.SPACES_BUCKET,
            Key=key,
            Body=content,
            ACL="public-read",
            ContentType=content_type,
            CacheControl=CACHE_CONTROL,
        )
    except (BotoCoreError, ClientError) as exc:
        raise ProviderError("Spaces upload failed") from exc
    return public_url(key)


def delete(key: str) -> None:
    client = _client()
    try:
        client.delete_object(Bucket=settings.SPACES_BUCKET, Key=key)
    except (BotoCoreError, ClientError) as exc:
        raise ProviderError("Spaces delete failed") from exc
