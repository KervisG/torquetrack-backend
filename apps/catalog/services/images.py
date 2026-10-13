"""Galería de fotos del producto: el panel sube, borra y reordena.

Una foto subida nunca se guarda tal cual: se abre con Pillow, se le quitan los
metadatos, se achica y se reescribe como WebP. Así pesa poco y lo que llega
al bucket es una imagen de verdad, no el archivo que mandó el navegador.
"""

from __future__ import annotations

import io
import logging

from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.audit.services import record_activity
from apps.catalog.models import Product, ProductImage
from apps.common.errors import error_payload
from apps.common.ids import random_id
from apps.integrations.exceptions import ProviderError, ProviderNotConfigured
from apps.integrations.storage import spaces

logger = logging.getLogger(__name__)

# El nginx del frontend corta el body en 5 MB.
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_SIDE = 1600
MAX_IMAGES_PER_PRODUCT = 12
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")
MAX_ALT_LENGTH = 200

FILE_REQUIRED = "Choose an image to upload"
FILE_TOO_LARGE = "The image must be 4 MB or smaller"
FILE_NOT_AN_IMAGE = "Upload a JPG, PNG or WebP image"
GALLERY_FULL = f"A product can have up to {MAX_IMAGES_PER_PRODUCT} images"
INVALID_ORDER = "order must list every image of the product once"
STORAGE_NOT_CONFIGURED = "Image storage is not configured: set the SPACES_* variables"
STORAGE_FAILED = "Could not reach the image storage. Try again."
PRODUCT_NOT_FOUND = "Product not found"
IMAGE_NOT_FOUND = "Image not found"


class InvalidImage(ValueError):
    pass


def process_image(content: bytes, *, max_side: int = MAX_IMAGE_SIDE) -> tuple[bytes, int, int]:
    """La foto como WebP, con el lado mayor en `max_side` como máximo.
    `InvalidImage` si no es un JPG, PNG o WebP legible."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in ALLOWED_FORMATS:
                raise InvalidImage(FILE_NOT_AN_IMAGE)
            # La cámara guarda la foto girada y anota el giro en el EXIF: se
            # aplica antes de descartar los metadatos.
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            image.thumbnail((max_side, max_side))
            output = io.BytesIO()
            image.save(output, "WEBP", quality=85, method=4)
            return output.getvalue(), image.width, image.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidImage(FILE_NOT_AN_IMAGE) from exc


def _rows(images, *, full: bool) -> list[dict]:
    rows = []
    for image in images:
        row = {"id": image.pk, "url": image.url, "alt": image.alt}
        if full:
            row |= {"position": image.position, "width": image.width, "height": image.height}
        rows.append(row)
    return rows


def serialize_images(product: Product, *, full: bool = False) -> list[dict]:
    """La galería en orden. `full` suma lo que usa el panel para ordenarla.
    Una lista de productos la pide con `prefetch_related("images")`."""
    return _rows(product.images.all(), full=full)


def _sync(product: Product) -> list[dict]:
    """Deja las posiciones seguidas desde 0 y la portada en `image`: el
    catálogo, el carrito y el checkout leen esa clave."""
    images = list(product.images.order_by("position", "id"))
    for position, image in enumerate(images):
        if image.position != position:
            image.position = position
            image.save(update_fields=["position"])
    attributes = dict(product.attributes or {})
    if images:
        attributes["image"] = images[0].url
    else:
        attributes.pop("image", None)
    product.attributes = attributes
    product.updated_at = timezone.now()
    product.save(update_fields=["attributes", "updated_at"])
    return _rows(images, full=True)


def _locked_product(product_id: str) -> Product | None:
    return Product.objects.select_for_update().filter(pk=product_id).first()


def add_product_image(product_id: str, upload, alt, actor_email: str) -> tuple[dict, int]:
    if upload is None:
        return error_payload(FILE_REQUIRED, "file"), 400
    if upload.size > MAX_IMAGE_BYTES:
        return error_payload(FILE_TOO_LARGE, "file"), 400
    try:
        content, width, height = process_image(upload.read())
    except InvalidImage as exc:
        return error_payload(str(exc), "file"), 400

    with transaction.atomic():
        product = _locked_product(product_id)
        if product is None:
            return {"error": PRODUCT_NOT_FOUND}, 404
        count = product.images.count()
        if count >= MAX_IMAGES_PER_PRODUCT:
            return error_payload(GALLERY_FULL, "file"), 400

        key = f"products/{product_id}/{random_id('IMG').lower()}.webp"
        try:
            url = spaces.upload(key=key, content=content, content_type="image/webp")
        except ProviderNotConfigured:
            return {"error": STORAGE_NOT_CONFIGURED}, 503
        except ProviderError as exc:
            logger.warning("Spaces upload for product %s failed: %s", product_id, exc)
            return {"error": STORAGE_FAILED}, 502

        ProductImage.objects.create(
            product=product,
            position=count,
            key=key,
            url=url,
            alt=str(alt or "").strip()[:MAX_ALT_LENGTH],
            width=width,
            height=height,
        )
        images = _sync(product)
        record_activity(
            actor=actor_email,
            action="PRODUCT_IMAGE_ADDED",
            entity_type="PRODUCT",
            entity_id=product_id,
            data={"key": key},
        )
    return {"ok": True, "images": images}, 201


def delete_product_image(product_id: str, image_id, actor_email: str) -> tuple[dict, int]:
    with transaction.atomic():
        product = _locked_product(product_id)
        if product is None:
            return {"error": PRODUCT_NOT_FOUND}, 404
        image = product.images.filter(pk=image_id).first()
        if image is None:
            return {"error": IMAGE_NOT_FOUND}, 404
        key = image.key
        image.delete()
        images = _sync(product)
        record_activity(
            actor=actor_email,
            action="PRODUCT_IMAGE_REMOVED",
            entity_type="PRODUCT",
            entity_id=product_id,
            data={"key": key},
        )
    try:
        spaces.delete(key)
    except ProviderError as exc:
        # La fila ya no existe: un objeto huérfano no rompe nada.
        logger.warning("Spaces delete of %s failed: %s", key, exc)
    return {"ok": True, "images": images}, 200


def reorder_product_images(product_id: str, order) -> tuple[dict, int]:
    """`order` son los ids de las fotos en el orden nuevo; la primera queda de
    portada."""
    with transaction.atomic():
        product = _locked_product(product_id)
        if product is None:
            return {"error": PRODUCT_NOT_FOUND}, 404
        images = {image.pk: image for image in product.images.all()}
        valid = (
            isinstance(order, list)
            and bool(order)
            and all(type(item) is int for item in order)
            and len(order) == len(set(order))
            and set(order) == set(images)
        )
        if not valid:
            return error_payload(INVALID_ORDER, "order"), 400
        for position, image_id in enumerate(order):
            images[image_id].position = position
            images[image_id].save(update_fields=["position"])
        return {"ok": True, "images": _sync(product)}, 200
