"""Galería de fotos del producto: el panel sube, borra y reordena; la primera
foto es la portada (`image`) y la tienda recibe la lista entera."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.catalog.models import Product, ProductImage
from apps.integrations.exceptions import ProviderError, ProviderNotConfigured
from tests.factories import activity_count, create_staff_user, session_client
from tests.fakes import SPACES, install_spaces

URL = "/api/admin/products/pump/images/"


def _photo(name="pump.jpg", size=(800, 600), image_format="JPEG", color="red"):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, image_format)
    content_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[image_format]
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


@pytest.fixture
def spaces(monkeypatch):
    return install_spaces(monkeypatch)


@pytest.fixture
def product(db):
    return Product.objects.create(
        id="pump", data={"id": "pump", "title": "Pump", "partNumber": "P1", "price": 100}
    )


@pytest.fixture
def client(db):
    create_staff_user("usr_img", permissions=["products.view", "products.edit"])
    return session_client("usr_img")[0]


def _upload(client, **fields):
    return client.post(URL, {"file": _photo(), **fields}, format="multipart")


# --- subir ------------------------------------------------------------------


def test_upload_stores_a_webp_and_returns_the_gallery(client, product, spaces):
    response = _upload(client, alt="Front view")

    assert response.status_code == 201
    (image,) = response.json()["images"]
    assert image["alt"] == "Front view"
    assert image["url"].startswith("https://cdn.test/products/pump/")
    assert image["url"].endswith(".webp")
    assert (image["width"], image["height"]) == (800, 600)
    (stored,) = spaces.objects.values()
    assert stored["content_type"] == "image/webp"
    assert Image.open(io.BytesIO(stored["content"])).format == "WEBP"
    assert activity_count(action="PRODUCT_IMAGE_ADDED", entity_id="pump") == 1


def test_a_large_photo_is_scaled_down(client, product, spaces):
    response = client.post(URL, {"file": _photo(size=(4000, 2000))}, format="multipart")

    (image,) = response.json()["images"]
    assert (image["width"], image["height"]) == (1600, 800)


def test_the_first_photo_becomes_the_cover(client, product, spaces):
    first = _upload(client).json()["images"][0]
    _upload(client)

    assert Product.objects.get(pk="pump").data["image"] == first["url"]
    assert [row.position for row in ProductImage.objects.order_by("position")] == [0, 1]


@pytest.mark.parametrize("image_format", ["PNG", "WEBP"])
def test_png_and_webp_are_accepted(client, product, spaces, image_format):
    response = client.post(
        URL,
        {"file": _photo(f"pump.{image_format.lower()}", image_format=image_format)},
        format="multipart",
    )

    assert response.status_code == 201


def test_a_file_that_is_not_an_image_is_rejected(client, product, spaces):
    fake = SimpleUploadedFile("pump.jpg", b"<?php echo 1; ?>", content_type="image/jpeg")

    response = client.post(URL, {"file": fake}, format="multipart")

    assert response.status_code == 400
    assert response.json() == {"error": "Upload a JPG, PNG or WebP image", "field": "file"}
    assert not spaces.objects
    assert not ProductImage.objects.exists()


def test_a_gif_is_rejected(client, product, spaces):
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, "GIF")
    gif = SimpleUploadedFile("pump.gif", buffer.getvalue(), content_type="image/gif")

    assert client.post(URL, {"file": gif}, format="multipart").status_code == 400


def test_a_photo_over_the_size_limit_is_rejected(client, product, spaces):
    big = SimpleUploadedFile("pump.jpg", b"x" * (4 * 1024 * 1024 + 1), content_type="image/jpeg")

    response = client.post(URL, {"file": big}, format="multipart")

    assert response.status_code == 400
    assert response.json() == {"error": "The image must be 4 MB or smaller", "field": "file"}


def test_upload_without_a_file_is_rejected(client, product, spaces):
    response = client.post(URL, {}, format="multipart")

    assert response.status_code == 400
    assert response.json() == {"error": "Choose an image to upload", "field": "file"}


def test_the_gallery_has_a_limit(client, product, spaces):
    for position in range(12):
        ProductImage.objects.create(
            product=product,
            position=position,
            key=f"k{position}",
            url=f"https://cdn.test/{position}",
        )

    response = _upload(client)

    assert response.status_code == 400
    assert response.json()["error"] == "A product can have up to 12 images"


def test_upload_for_an_unknown_product_is_404(client, spaces):
    assert _upload(client).status_code == 404


def test_upload_requires_the_edit_permission(product, spaces):
    create_staff_user("usr_view", permissions=["products.view"])
    viewer = session_client("usr_view")[0]

    assert _upload(viewer).status_code == 403
    assert _upload(APIClient()).status_code in (401, 403)


def test_storage_without_keys_answers_503(client, product, monkeypatch):
    def _missing(**kwargs):
        raise ProviderNotConfigured("SPACES_KEY is not set")

    monkeypatch.setattr(f"{SPACES}.upload", _missing)

    response = _upload(client)

    assert response.status_code == 503
    assert "SPACES" in response.json()["error"]
    assert not ProductImage.objects.exists()


def test_a_storage_failure_answers_502_and_saves_nothing(client, product, monkeypatch):
    def _down(**kwargs):
        raise ProviderError("Spaces is down")

    monkeypatch.setattr(f"{SPACES}.upload", _down)

    response = _upload(client)

    assert response.status_code == 502
    assert not ProductImage.objects.exists()


# --- borrar y reordenar -----------------------------------------------------


def test_delete_removes_the_photo_and_the_next_one_becomes_the_cover(client, product, spaces):
    first = _upload(client).json()["images"][0]
    second = _upload(client).json()["images"][1]

    response = client.delete(f"{URL}{first['id']}/")

    assert response.status_code == 200
    assert [image["id"] for image in response.json()["images"]] == [second["id"]]
    assert response.json()["images"][0]["position"] == 0
    assert Product.objects.get(pk="pump").data["image"] == second["url"]
    assert len(spaces.deleted) == 1 and len(spaces.objects) == 1
    assert activity_count(action="PRODUCT_IMAGE_REMOVED", entity_id="pump") == 1


def test_deleting_the_last_photo_clears_the_cover(client, product, spaces):
    image = _upload(client).json()["images"][0]

    client.delete(f"{URL}{image['id']}/")

    assert "image" not in Product.objects.get(pk="pump").data


def test_delete_of_a_photo_of_another_product_is_404(client, product, spaces):
    other = Product.objects.create(id="other", data={"title": "Other"})
    image = ProductImage.objects.create(
        product=other, position=0, key="k", url="https://cdn.test/k"
    )

    assert client.delete(f"{URL}{image.pk}/").status_code == 404
    assert ProductImage.objects.filter(pk=image.pk).exists()


def test_reorder_moves_the_cover(client, product, spaces):
    first = _upload(client).json()["images"][0]
    second = _upload(client).json()["images"][1]

    response = client.patch(URL, {"order": [second["id"], first["id"]]}, format="json")

    assert response.status_code == 200
    assert [image["id"] for image in response.json()["images"]] == [second["id"], first["id"]]
    assert Product.objects.get(pk="pump").data["image"] == second["url"]


@pytest.mark.parametrize("order", [[], [999], "abc", None])
def test_reorder_needs_exactly_the_photos_of_the_product(client, product, spaces, order):
    _upload(client)

    response = client.patch(URL, {"order": order}, format="json")

    assert response.status_code == 400
    assert response.json() == {
        "error": "order must list every image of the product once",
        "field": "order",
    }


# --- lectura ----------------------------------------------------------------


def test_the_store_and_the_panel_receive_the_gallery(client, product, spaces):
    uploaded = _upload(client, alt="Front").json()["images"][0]
    expected = [{"id": uploaded["id"], "url": uploaded["url"], "alt": "Front"}]

    detail = APIClient().get("/api/products/pump/").json()
    listed = APIClient().get("/api/products/").json()["results"][0]
    (panel,) = client.get("/api/admin/products/").json()

    assert detail["images"] == expected
    assert listed["images"] == expected
    assert detail["image"] == uploaded["url"]
    assert [image["id"] for image in panel["images"]] == [uploaded["id"]]


def test_a_product_without_photos_has_no_images_key(product):
    assert "images" not in APIClient().get("/api/products/pump/").json()


def test_editing_the_product_keeps_the_cover_of_the_gallery(client, product, spaces):
    create_staff_user("usr_price", permissions=["products.edit", "pricing.edit"])
    editor = session_client("usr_price")[0]
    cover = _upload(client).json()["images"][0]["url"]

    response = editor.put(
        "/api/admin/products/pump/",
        {"title": "Pump", "partNumber": "P1", "price": 100, "image": "https://other.test/x.png"},
        format="json",
    )

    assert response.status_code == 200
    assert Product.objects.get(pk="pump").data["image"] == cover


def test_saving_the_product_never_stores_the_gallery_in_its_attributes(client, product, spaces):
    create_staff_user("usr_full", permissions=["products.edit", "pricing.edit"])
    editor = session_client("usr_full")[0]
    images = _upload(client).json()["images"]

    editor.put(
        "/api/admin/products/pump/",
        {"title": "Pump", "partNumber": "P1", "price": 100, "images": images},
        format="json",
    )

    assert "images" not in Product.objects.get(pk="pump").attributes
