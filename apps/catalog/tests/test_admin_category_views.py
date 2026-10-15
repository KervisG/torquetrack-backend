"""Categorías del panel: `GET`/`POST /api/admin/categories/` y `PATCH
/api/admin/categories/<id>/`.

Listar pide `products.view`; crear y mover de línea, `products.edit`. Una
categoría es el texto que llevan los productos en `category`, cruzado por su
forma canónica (`Fuel Injectors` e `Injector` son `INJECTOR`). `line` es la
sección de la portada donde sale; una categoría que nace con un producto cae
en `OTHER`. Sin proveedores que mockear.
"""

import io
import json
from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.core.management import CommandError, call_command

from apps.catalog.models import Brand, Category, Product, ProductLine
from tests.factories import activity_count, create_staff_user, session_client

URL = "/api/admin/categories/"


def _insert_product(product_id, category=None, active=True):
    data = {"id": product_id, "title": product_id, "partNumber": "P1", "price": 100}
    if category:
        data["category"] = category
    return Product.objects.create(id=product_id, data=data, active=active)


@pytest.fixture
def client(db):
    create_staff_user(
        "usr_cat", permissions=["products.view", "products.edit", "pricing.edit"]
    )
    return session_client("usr_cat")[0]


@pytest.fixture
def viewer(db):
    create_staff_user("usr_cat_view", permissions=["products.view"])
    return session_client("usr_cat_view")[0]


def test_product_line_values_are_the_contract_with_the_spa():
    assert ProductLine.values == ["FUEL_SYSTEM", "TURBO_AIR", "EMISSIONS", "OTHER"]


# --- listar -----------------------------------------------------------------


def test_list_returns_categories_by_name_with_their_product_count(viewer):
    Category.objects.create(name="Turbo", value="TURBO", line="TURBO_AIR")
    Category.objects.create(name="Injector", value="INJECTOR", line="FUEL_SYSTEM")
    _insert_product("p1", "Injector")
    _insert_product("p2", "Fuel Injectors", active=False)

    response = viewer.get(URL)

    assert response.status_code == 200
    rows = response.json()
    assert [row["name"] for row in rows] == ["Injector", "Turbo"]
    assert rows[0] == {
        "id": Category.objects.get(value="INJECTOR").pk,
        "name": "Injector",
        "value": "INJECTOR",
        "line": "FUEL_SYSTEM",
        "productCount": 2,
    }
    assert rows[1]["productCount"] == 0


def test_list_requires_products_view(db):
    create_staff_user("usr_cat_none", permissions=["orders.view"])

    assert session_client("usr_cat_none")[0].get(URL).status_code == 403


# --- crear ------------------------------------------------------------------


def test_create_adds_a_category_in_its_line(client):
    response = client.post(URL, {"name": "  Glow plug ", "line": "FUEL_SYSTEM"}, format="json")

    assert response.status_code == 201
    category = Category.objects.get()
    assert response.json() == {
        "ok": True,
        "category": {
            "id": category.pk,
            "name": "Glow plug",
            "value": "GLOW PLUG",
            "line": "FUEL_SYSTEM",
            "productCount": 0,
        },
    }
    assert activity_count(action="CATEGORY_CREATED", entity_id=str(category.pk)) == 1


def test_create_without_a_line_lands_in_other(client):
    response = client.post(URL, {"name": "Glow plug"}, format="json")

    assert response.status_code == 201
    assert response.json()["category"]["line"] == "OTHER"


def test_create_requires_products_edit(viewer):
    assert viewer.post(URL, {"name": "Glow plug"}, format="json").status_code == 403
    assert not Category.objects.exists()


@pytest.mark.parametrize("name", ["", "   ", None, 7, "---"])
def test_create_requires_a_name(client, name):
    response = client.post(URL, {"name": name}, format="json")

    assert response.status_code == 400
    assert response.json() == {"error": "Category name is required", "field": "name"}


def test_create_rejects_another_spelling_of_an_existing_category(client):
    Category.objects.create(name="Injector", value="INJECTOR")

    response = client.post(URL, {"name": "fuel injectors"}, format="json")

    assert response.status_code == 400
    assert response.json() == {
        "error": "A category with this name already exists",
        "field": "name",
    }
    assert Category.objects.count() == 1


def test_create_rejects_an_unknown_line(client):
    response = client.post(URL, {"name": "Glow plug", "line": "BRAKES"}, format="json")

    assert response.status_code == 400
    assert response.json() == {
        "error": "line must be one of FUEL_SYSTEM, TURBO_AIR, EMISSIONS, OTHER",
        "field": "line",
    }


# --- mover de línea ---------------------------------------------------------


def test_patch_moves_a_category_to_another_line(client):
    category = Category.objects.create(name="Glow plug", value="GLOW PLUG")

    response = client.patch(f"{URL}{category.pk}/", {"line": "FUEL_SYSTEM"}, format="json")

    assert response.status_code == 200
    assert response.json()["category"]["line"] == "FUEL_SYSTEM"
    category.refresh_from_db()
    assert category.line == "FUEL_SYSTEM"
    assert activity_count(action="CATEGORY_LINE_CHANGED", entity_id=str(category.pk)) == 1


@pytest.mark.parametrize("body", [{}, {"line": "BRAKES"}, {"line": None}])
def test_patch_requires_a_known_line(client, body):
    category = Category.objects.create(name="Glow plug", value="GLOW PLUG")

    response = client.patch(f"{URL}{category.pk}/", body, format="json")

    assert response.status_code == 400
    assert response.json()["field"] == "line"


def test_patch_of_an_unknown_category_is_404(client):
    response = client.patch(f"{URL}999/", {"line": "OTHER"}, format="json")

    assert response.status_code == 404
    assert response.json() == {"error": "Category not found"}


def test_patch_requires_products_edit(viewer):
    category = Category.objects.create(name="Glow plug", value="GLOW PLUG")

    response = viewer.patch(f"{URL}{category.pk}/", {"line": "FUEL_SYSTEM"}, format="json")

    assert response.status_code == 403


# --- las categorías nacen con los productos ----------------------------------


def test_saving_a_product_creates_its_missing_category_in_other(client):
    response = client.put(
        "/api/admin/products/plug/",
        {"title": "Plug", "partNumber": "P1", "price": 100, "category": "Glow plug"},
        format="json",
    )

    assert response.status_code == 200
    category = Category.objects.get()
    assert (category.name, category.value, category.line) == ("Glow plug", "GLOW PLUG", "OTHER")


def test_saving_a_product_keeps_the_line_of_an_existing_category(client):
    Category.objects.create(name="Injector", value="INJECTOR", line="FUEL_SYSTEM")

    client.put(
        "/api/admin/products/inj/",
        {"title": "Inj", "partNumber": "P1", "price": 100, "category": "Fuel Injectors"},
        format="json",
    )

    category = Category.objects.get()
    assert (category.name, category.line) == ("Injector", "FUEL_SYSTEM")


def test_the_seed_migration_puts_known_categories_in_their_line(db):
    seed = import_module("apps.catalog.migrations.0009_seed_categories").seed_categories
    _insert_product("p1", "Fuel Injectors")
    _insert_product("p2", "Injector")
    _insert_product("p3", "Turbo")
    _insert_product("p4", "DPF")
    _insert_product("p5", "Glow plug")
    _insert_product("p6")

    seed(django_apps, None)

    assert dict(Category.objects.values_list("value", "line")) == {
        "INJECTOR": "FUEL_SYSTEM",
        "TURBO": "TURBO_AIR",
        "DPF": "EMISSIONS",
        "GLOW PLUG": "OTHER",
    }


@pytest.mark.parametrize("flags", [{}, {"only_missing": True}])
def test_import_catalog_creates_the_brands_and_categories_of_its_products(db, tmp_path, flags):
    products = tmp_path / "products.json"
    products.write_text(
        '[{"id": "pump", "title": "Pump", "partNumber": "P1", "price": 10,'
        ' "manufacturer": "Alliant Power / Bosch", "category": "Glow plug"}]',
        encoding="utf-8",
    )

    categories = _write_categories(tmp_path, [])

    call_command(
        "import_catalog",
        products=products,
        categories=categories,
        stdout=io.StringIO(),
        **flags,
    )

    assert sorted(Brand.objects.values_list("name", flat=True)) == ["Alliant Power", "Bosch"]
    assert list(Category.objects.values_list("value", flat=True)) == ["GLOW PLUG"]


# --- categories.json: semilla y ZIP del panel ---------------------------------


def _write_categories(tmp_path, rows):
    path = tmp_path / "categories.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _write_products(tmp_path, rows):
    path = tmp_path / "products.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


@pytest.mark.parametrize("flags", [{}, {"only_missing": True}])
def test_import_catalog_loads_the_seed_categories_in_their_line(db, tmp_path, flags):
    products = _write_products(tmp_path, [])

    call_command("import_catalog", products=products, stdout=io.StringIO(), **flags)

    lines = dict(Category.objects.values_list("value", "line"))
    assert lines["INJECTOR"] == "FUEL_SYSTEM"
    assert lines["TURBO"] == "TURBO_AIR"
    assert lines["DPF"] == "EMISSIONS"


def test_import_catalog_creates_categories_before_their_products(db, tmp_path):
    # Sin el archivo, el producto dejaría "Glow plug" en `OTHER`.
    products = _write_products(
        tmp_path,
        [{"id": "plug", "title": "Plug", "partNumber": "P1", "price": 10, "category": "glow plug"}],
    )
    categories = _write_categories(tmp_path, [{"name": "Glow Plug", "line": "FUEL_SYSTEM"}])

    call_command(
        "import_catalog", products=products, categories=categories, stdout=io.StringIO()
    )

    category = Category.objects.get()
    assert (category.name, category.value, category.line) == (
        "Glow Plug",
        "GLOW PLUG",
        "FUEL_SYSTEM",
    )


@pytest.mark.parametrize(("flags", "line"), [({}, "EMISSIONS"), ({"only_missing": True}, "OTHER")])
def test_only_missing_keeps_the_line_chosen_in_the_panel(db, tmp_path, flags, line):
    Category.objects.create(name="DPF", value="DPF", line="OTHER")
    products = _write_products(tmp_path, [])
    categories = _write_categories(tmp_path, [{"name": "DPF", "line": "EMISSIONS"}])

    call_command(
        "import_catalog", products=products, categories=categories, stdout=io.StringIO(), **flags
    )

    assert Category.objects.get(value="DPF").line == line


@pytest.mark.parametrize(
    "rows", [[{"name": "Glow plug", "line": "BRAKES"}], [{"name": "  "}], [{"line": "OTHER"}], {}]
)
def test_import_catalog_rejects_invalid_categories_without_writing(db, tmp_path, rows):
    products = _write_products(
        tmp_path, [{"id": "plug", "title": "Plug", "partNumber": "P1", "price": 10}]
    )
    categories = _write_categories(tmp_path, rows)

    with pytest.raises(CommandError, match="Invalid categories"):
        call_command(
            "import_catalog", products=products, categories=categories, stdout=io.StringIO()
        )

    assert not Product.objects.exists()
    assert not Category.objects.exists()


def test_migration_0010_moves_known_categories_out_of_other(db):
    restore = import_module(
        "apps.catalog.migrations.0010_default_category_lines"
    ).restore_default_lines
    Category.objects.create(name="Injector", value="INJECTOR", line="OTHER")
    Category.objects.create(name="Turbo", value="TURBO", line="FUEL_SYSTEM")
    Category.objects.create(name="Glow plug", value="GLOW PLUG", line="OTHER")

    restore(django_apps, None)

    assert dict(Category.objects.values_list("value", "line")) == {
        "INJECTOR": "FUEL_SYSTEM",
        # Una sección elegida en el panel no se toca.
        "TURBO": "FUEL_SYSTEM",
        "GLOW PLUG": "OTHER",
    }
