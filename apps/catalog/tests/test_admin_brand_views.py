"""Marcas del panel: `GET`/`POST /api/admin/brands/`, `PATCH
/api/admin/brands/<id>/` y `POST`/`DELETE /api/admin/brands/<id>/logo/`.

Listar pide `products.view`; el resto, `products.edit`. Una marca es el nombre
que llevan los productos en `manufacturer` (`Alliant Power / Bosch` son dos):
desactivarla desactiva esos productos y activarla los vuelve a activar. Spaces
se falsea con `install_spaces`; ningún test llega al bucket.
"""

import io
from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from PIL import Image

from apps.catalog.models import Brand, Product
from apps.integrations.exceptions import ProviderNotConfigured
from tests.factories import activity_count, create_staff_user, session_client
from tests.fakes import SPACES, install_spaces

URL = "/api/admin/brands/"


def _logo(size=(900, 300), image_format="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", size, "blue").save(buffer, image_format)
    return SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png")


def _insert_product(product_id, manufacturer=None, active=True):
    data = {"id": product_id, "title": product_id, "partNumber": "P1", "price": 100}
    if manufacturer:
        data["manufacturer"] = manufacturer
    return Product.objects.create(id=product_id, data=data, active=active)


@pytest.fixture
def spaces(monkeypatch):
    return install_spaces(monkeypatch)


@pytest.fixture
def client(db):
    create_staff_user(
        "usr_brand", permissions=["products.view", "products.edit", "pricing.edit"]
    )
    return session_client("usr_brand")[0]


@pytest.fixture
def viewer(db):
    create_staff_user("usr_brand_view", permissions=["products.view"])
    return session_client("usr_brand_view")[0]


# --- listar -----------------------------------------------------------------


def test_list_returns_brands_by_name_with_their_product_count(viewer):
    Brand.objects.create(name="Garrett")
    Brand.objects.create(name="Bosch", active=False)
    _insert_product("p1", "Alliant Power / Bosch")
    _insert_product("p2", "bosch", active=False)

    response = viewer.get(URL)

    assert response.status_code == 200
    rows = response.json()
    assert [row["name"] for row in rows] == ["Bosch", "Garrett"]
    assert rows[0] == {
        "id": Brand.objects.get(name="Bosch").pk,
        "name": "Bosch",
        "logo": None,
        "active": False,
        "productCount": 2,
    }
    assert rows[1]["productCount"] == 0


def test_list_requires_products_view(db):
    create_staff_user("usr_brand_none", permissions=["orders.view"])

    assert session_client("usr_brand_none")[0].get(URL).status_code == 403


# --- crear ------------------------------------------------------------------


def test_create_adds_an_active_brand(client):
    response = client.post(URL, {"name": "  Garrett  "}, format="json")

    assert response.status_code == 201
    brand = Brand.objects.get()
    assert response.json() == {
        "ok": True,
        "brand": {
            "id": brand.pk,
            "name": "Garrett",
            "logo": None,
            "active": True,
            "productCount": 0,
        },
    }
    assert activity_count(action="BRAND_CREATED", entity_id=str(brand.pk)) == 1


def test_create_requires_products_edit(viewer):
    assert viewer.post(URL, {"name": "Garrett"}, format="json").status_code == 403
    assert not Brand.objects.exists()


@pytest.mark.parametrize("name", ["", "   ", None, 7])
def test_create_requires_a_name(client, name):
    response = client.post(URL, {"name": name}, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": "Brand name is required", "field": "name"}


def test_create_rejects_a_name_that_differs_only_in_case(client):
    Brand.objects.create(name="Bosch")

    response = client.post(URL, {"name": "BOSCH"}, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": "A brand with this name already exists", "field": "name"}
    assert Brand.objects.count() == 1


def test_create_rejects_a_slash_because_it_separates_brands(client):
    response = client.post(URL, {"name": "Alliant Power / Bosch"}, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": "A brand name cannot contain '/'", "field": "name"}


# --- activar y desactivar ---------------------------------------------------


def test_deactivating_a_brand_deactivates_its_products(client):
    brand = Brand.objects.create(name="Alliant Power")
    _insert_product("only", "Alliant Power")
    _insert_product("shared", "alliant power / Bosch")
    _insert_product("other", "Bosch")
    _insert_product("none")

    response = client.patch(f"{URL}{brand.pk}/", {"active": False}, format="json")

    assert response.status_code == 200
    assert response.json()["brand"]["active"] is False
    assert response.json()["brand"]["productCount"] == 2
    brand.refresh_from_db()
    assert brand.active is False
    active = dict(Product.objects.values_list("pk", "active"))
    assert active == {"only": False, "shared": False, "other": True, "none": True}
    assert activity_count(action="BRAND_DEACTIVATED", entity_id=str(brand.pk)) == 1


def test_activating_a_brand_activates_its_products(client):
    brand = Brand.objects.create(name="Alliant Power", active=False)
    _insert_product("only", "Alliant Power", active=False)
    _insert_product("other", "Bosch", active=False)

    response = client.patch(f"{URL}{brand.pk}/", {"active": True}, format="json")

    assert response.status_code == 200
    brand.refresh_from_db()
    assert brand.active is True
    assert dict(Product.objects.values_list("pk", "active")) == {"only": True, "other": False}
    assert activity_count(action="BRAND_ACTIVATED", entity_id=str(brand.pk)) == 1


@pytest.mark.parametrize("body", [{}, {"active": "false"}, {"active": None}])
def test_patch_requires_a_boolean_active(client, body):
    brand = Brand.objects.create(name="Bosch")

    response = client.patch(f"{URL}{brand.pk}/", body, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": "active must be a boolean", "field": "active"}


def test_patch_of_an_unknown_brand_is_404(client):
    response = client.patch(f"{URL}999/", {"active": False}, format="json")

    assert response.status_code == 404
    assert response.json() == {"error": "Brand not found"}


def test_patch_requires_products_edit(viewer):
    brand = Brand.objects.create(name="Bosch")

    response = viewer.patch(f"{URL}{brand.pk}/", {"active": False}, format="json")

    assert response.status_code == 403
    brand.refresh_from_db()
    assert brand.active is True


# --- logo -------------------------------------------------------------------


def test_logo_upload_stores_a_small_webp(client, spaces):
    brand = Brand.objects.create(name="Bosch")

    response = client.post(f"{URL}{brand.pk}/logo/", {"file": _logo()}, format="multipart")

    assert response.status_code == 200
    logo = response.json()["brand"]["logo"]
    assert logo.startswith(f"https://cdn.test/brands/{brand.pk}/")
    assert logo.endswith(".webp")
    (stored,) = spaces.objects.values()
    image = Image.open(io.BytesIO(stored["content"]))
    assert image.format == "WEBP"
    assert image.size == (400, 133)
    assert activity_count(action="BRAND_LOGO_UPDATED", entity_id=str(brand.pk)) == 1


def test_a_new_logo_replaces_the_old_one(client, spaces):
    brand = Brand.objects.create(name="Bosch")
    first = client.post(f"{URL}{brand.pk}/logo/", {"file": _logo()}, format="multipart")
    old_key = Brand.objects.get().logo_key

    second = client.post(f"{URL}{brand.pk}/logo/", {"file": _logo()}, format="multipart")

    assert second.json()["brand"]["logo"] != first.json()["brand"]["logo"]
    assert spaces.deleted == [old_key]
    assert list(spaces.objects) == [Brand.objects.get().logo_key]


def test_logo_upload_rejects_a_file_that_is_not_an_image(client, spaces):
    brand = Brand.objects.create(name="Bosch")
    fake = SimpleUploadedFile("logo.png", b"<?php echo 1; ?>", content_type="image/png")

    response = client.post(f"{URL}{brand.pk}/logo/", {"file": fake}, format="multipart")

    assert response.status_code == 400
    assert response.json() == {"error": "Upload a JPG, PNG or WebP image", "field": "file"}
    assert not spaces.objects


def test_logo_upload_without_a_file_is_rejected(client, spaces):
    brand = Brand.objects.create(name="Bosch")

    response = client.post(f"{URL}{brand.pk}/logo/", {}, format="multipart")

    assert response.status_code == 400
    assert response.json() == {"error": "Choose an image to upload", "field": "file"}


def test_logo_upload_without_storage_is_503(client, monkeypatch):
    brand = Brand.objects.create(name="Bosch")

    def _not_configured(**kwargs):
        raise ProviderNotConfigured("no bucket")

    monkeypatch.setattr(f"{SPACES}.upload", _not_configured)

    response = client.post(f"{URL}{brand.pk}/logo/", {"file": _logo()}, format="multipart")

    assert response.status_code == 503
    assert Brand.objects.get().logo_url == ""


def test_logo_upload_for_an_unknown_brand_is_404(client, spaces):
    response = client.post(f"{URL}999/logo/", {"file": _logo()}, format="multipart")

    assert response.status_code == 404
    assert not spaces.objects


def test_logo_delete_clears_it(client, spaces):
    brand = Brand.objects.create(name="Bosch")
    client.post(f"{URL}{brand.pk}/logo/", {"file": _logo()}, format="multipart")
    key = Brand.objects.get().logo_key

    response = client.delete(f"{URL}{brand.pk}/logo/")

    assert response.status_code == 200
    assert response.json()["brand"]["logo"] is None
    assert spaces.deleted == [key]
    assert Brand.objects.get().logo_key == ""


def test_logo_endpoints_require_products_edit(viewer, spaces):
    brand = Brand.objects.create(name="Bosch")

    upload = viewer.post(f"{URL}{brand.pk}/logo/", {"file": _logo()}, format="multipart")

    assert upload.status_code == 403
    assert viewer.delete(f"{URL}{brand.pk}/logo/").status_code == 403
    assert not spaces.objects


# --- las marcas nacen con los productos --------------------------------------


def test_saving_a_product_creates_its_missing_brands(client):
    Brand.objects.create(name="Bosch")

    response = client.put(
        "/api/admin/products/pump/",
        {"title": "Pump", "partNumber": "P1", "price": 100, "manufacturer": "Garrett / bosch"},
        format="json",
    )

    assert response.status_code == 200
    assert sorted(Brand.objects.values_list("name", flat=True)) == ["Bosch", "Garrett"]


def test_the_seed_migration_creates_one_brand_per_existing_name(db):
    seed = import_module("apps.catalog.migrations.0007_seed_brands").seed_brands
    Brand.objects.create(name="Garrett")
    _insert_product("p1", "Alliant Power / Bosch")
    _insert_product("p2", "BOSCH")
    _insert_product("p3", "garrett")
    _insert_product("p4")

    seed(django_apps, None)

    assert sorted(Brand.objects.values_list("name", flat=True)) == [
        "Alliant Power",
        "Bosch",
        "Garrett",
    ]


def test_import_catalog_creates_the_brands_of_its_products(db, tmp_path):
    products = tmp_path / "products.json"
    products.write_text(
        '[{"id": "pump", "title": "Pump", "partNumber": "P1", "price": 10,'
        ' "manufacturer": "Alliant Power / Bosch"}]',
        encoding="utf-8",
    )

    call_command("import_catalog", products=products, stdout=io.StringIO())

    assert sorted(Brand.objects.values_list("name", flat=True)) == ["Alliant Power", "Bosch"]
