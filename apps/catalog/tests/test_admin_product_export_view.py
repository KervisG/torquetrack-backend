"""`GET /api/admin/products/export/` con `products.view`: ZIP con
`products.json`, `applications.json` y las imágenes locales (`image/<archivo>`).

Sin proveedores que mockear. Las imágenes se leen con los finders de
`staticfiles`, así que los tests apuntan `STATICFILES_DIRS` a un directorio
temporal y vacían la cache de finders antes y después. Se assertea a propósito
que el ZIP vuelve a cargarse con `import_catalog` (ida y vuelta) y que una URL
externa de imagen no se descarga.
"""
import io
import json
import zipfile
from io import StringIO

import pytest
from django.contrib.staticfiles import finders
from django.core.management import call_command

from apps.catalog.models import Application, Product
from apps.catalog.services import application_codes
from apps.common.business_day import store_today
from tests.factories import create_staff_user, session_client

URL = "/api/admin/products/export/"


@pytest.fixture
def static_dir(tmp_path, settings):
    root = tmp_path / "static"
    (root / "image").mkdir(parents=True)
    settings.STATICFILES_DIRS = [root]
    finders.get_finder.cache_clear()
    yield root
    finders.get_finder.cache_clear()


def _client(user_id, permissions):
    create_staff_user(user_id, permissions=permissions)
    client, _ = session_client(user_id)
    return client


def _insert_product(product_id, *, active=True, **data):
    return Product.objects.create(
        id=product_id,
        data={"id": product_id, "title": f"Part {product_id}", "price": 10, **data},
        active=active,
    )


def _insert_application(code, **data):
    return Application.objects.create(code=code, data={"id": code, "make": "Ford", **data})


def _archive(response) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(response.content))


def _json(archive, name):
    return json.loads(archive.read(name).decode("utf-8"))


@pytest.mark.django_db
def test_export_requires_products_view():
    client = _client("usr_export_no_perm", ["orders.view"])

    response = client.get(URL)

    assert response.status_code == 403
    assert "error" in response.json()


@pytest.mark.django_db
def test_export_rejects_anonymous_requests():
    from rest_framework.test import APIClient

    response = APIClient().get(URL)

    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_export_returns_a_dated_zip_attachment(static_dir):
    client = _client("usr_export", ["products.view"])

    response = client.get(URL)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    expected = f'attachment; filename="torquetrack-catalog-{store_today().isoformat()}.zip"'
    assert response["Content-Disposition"] == expected
    assert response["Cache-Control"] == "no-store"
    assert sorted(_archive(response).namelist()) == ["applications.json", "products.json"]


@pytest.mark.django_db
def test_export_includes_active_and_inactive_products_with_fitment(static_dir):
    application = _insert_application("ford-73-1994-1997")
    on = _insert_product("on", applicationIds=["stale-code"])
    on.applications.set([application])
    _insert_product("off", active=False, slug="ignored")
    client = _client("usr_export_all", ["products.view"])

    archive = _archive(client.get(URL))

    products = {row["id"]: row for row in _json(archive, "products.json")}
    assert products["on"]["active"] is True
    # El fitment sale de `ProductFitment`, no de un `applicationIds` viejo de `data`.
    assert products["on"]["applicationIds"] == ["ford-73-1994-1997"]
    assert products["off"]["active"] is False
    assert "applicationIds" not in products["off"]
    assert "slug" not in products["off"]
    assert _json(archive, "applications.json") == [
        {"id": "ford-73-1994-1997", "make": "Ford"}
    ]


@pytest.mark.django_db
def test_export_hides_cost_fields_without_costs_view(static_dir):
    _insert_product("costly", purchaseCost=40, supplier="Acme", supplierUrl="https://a.test")
    client = _client("usr_export_no_costs", ["products.view"])

    row = _json(_archive(client.get(URL)), "products.json")[0]

    assert row["price"] == 10
    for field in ("purchaseCost", "supplier", "supplierUrl"):
        assert field not in row


@pytest.mark.django_db
def test_export_includes_cost_fields_with_costs_view(static_dir):
    _insert_product("costly", purchaseCost=40, supplier="Acme")
    client = _client("usr_export_costs", ["products.view", "costs.view"])

    row = _json(_archive(client.get(URL)), "products.json")[0]

    assert row["purchaseCost"] == 40
    assert row["supplier"] == "Acme"


@pytest.mark.django_db
def test_export_packs_local_images_and_lists_missing_ones(static_dir):
    (static_dir / "image" / "pump.png").write_bytes(b"\x89PNG fake")
    _insert_product("with-image", image="/static/image/pump.png")
    _insert_product("same-image", image="/static/image/pump.png")
    _insert_product("lost-image", image="/static/image/lost.png")
    _insert_product("escape", image="/static/image/../../secret.txt")
    _insert_product("remote", image="https://placehold.co/640x480")
    client = _client("usr_export_images", ["products.view"])

    archive = _archive(client.get(URL))

    names = archive.namelist()
    assert archive.read("image/pump.png") == b"\x89PNG fake"
    assert names.count("image/pump.png") == 1
    assert not any("secret" in name for name in names)
    missing = archive.read("missing-images.txt").decode("utf-8").splitlines()
    assert "lost-image: /static/image/lost.png" in missing
    assert "escape: /static/image/../../secret.txt" in missing
    assert not any(line.startswith("remote") for line in missing)
    products = {row["id"]: row for row in _json(archive, "products.json")}
    # La URL externa queda tal cual en el JSON y no se descarga.
    assert products["remote"]["image"] == "https://placehold.co/640x480"


@pytest.mark.django_db
def test_exported_catalog_round_trips_through_import_catalog(static_dir, tmp_path):
    application = _insert_application("ram-59-cummins-2003-2007", yearFrom=2003)
    linked = _insert_product("linked", partNumber="LP-1", purchaseCost=5)
    linked.applications.set([application])
    _insert_product("retired", active=False, partNumber="RT-1")
    client = _client("usr_export_round_trip", ["products.view", "costs.view"])
    archive = _archive(client.get(URL))
    products_path = tmp_path / "products.json"
    applications_path = tmp_path / "applications.json"
    products_path.write_bytes(archive.read("products.json"))
    applications_path.write_bytes(archive.read("applications.json"))
    before = {
        product.pk: (product.data, product.active)
        for product in Product.objects.all()
    }
    Product.objects.all().delete()
    Application.objects.all().delete()

    call_command(
        "import_catalog",
        products=products_path,
        applications=applications_path,
        stdout=StringIO(),
    )

    restored = {product.pk: product for product in Product.objects.all()}
    assert set(restored) == set(before)
    assert restored["linked"].active is True
    assert restored["retired"].active is False
    assert application_codes(restored["linked"]) == ["ram-59-cummins-2003-2007"]
    assert restored["linked"].data["purchaseCost"] == 5
    assert "active" not in restored["retired"].data
    assert Application.objects.get(code="ram-59-cummins-2003-2007").data["yearFrom"] == 2003
