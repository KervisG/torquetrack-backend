"""Se corre contra los JSON reales de la semilla, no contra copias reducidas:
también protege que sigan siendo importables."""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.catalog.management.commands.import_catalog import DATA_DIR
from apps.catalog.models import Application, Product


def _load(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _run():
    out = StringIO()
    call_command("import_catalog", stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_imports_seed_catalog_into_empty_database():
    products = _load("products.json")
    applications = _load("applications.json")

    output = _run()

    assert Product.objects.count() == len(products)
    assert Product.objects.filter(active=True).count() == len(products)
    assert Application.objects.count() == len(applications)
    first = products[0]
    assert Product.objects.get(pk=str(first["id"])).data == first
    assert f"Products imported: {len(products)}" in output
    assert f"Applications imported: {len(applications)}" in output


@pytest.mark.django_db
def test_import_is_idempotent():
    products = _load("products.json")
    applications = _load("applications.json")

    _run()
    _run()

    assert Product.objects.count() == len(products)
    assert Application.objects.count() == len(applications)


@pytest.mark.django_db
def test_import_reactivates_and_overwrites_existing_product():
    first = _load("products.json")[0]
    Product.objects.create(id=str(first["id"]), data={"title": "Stale"}, active=False)

    _run()

    product = Product.objects.get(pk=str(first["id"]))
    assert product.active is True
    assert product.data == first


@pytest.mark.django_db
def test_import_keeps_products_missing_from_seed():
    # Un producto creado desde el panel no está en la semilla; la importación
    # no lo borra ni lo desactiva.
    Product.objects.create(id="panel-only-part", data={"title": "Panel Part"}, active=True)

    _run()

    assert Product.objects.get(pk="panel-only-part").active is True


def test_every_seed_product_has_a_positive_price():
    unpriced = [p["id"] for p in _load("products.json") if not (p.get("price") or 0) > 0]

    assert unpriced == []


@pytest.mark.django_db
def test_import_aborts_without_writing_when_a_product_has_no_price(tmp_path):
    products = tmp_path / "products.json"
    products.write_text(
        json.dumps([{"id": "priced", "price": 10}, {"id": "unpriced", "price": 0}]),
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="unpriced"):
        call_command("import_catalog", products=products, stdout=StringIO())

    assert not Product.objects.exists()


def _write_products(tmp_path, products):
    path = tmp_path / "products.json"
    path.write_text(json.dumps(products), encoding="utf-8")
    return path


@pytest.mark.django_db
def test_import_lists_every_unpriced_product_with_the_count(tmp_path):
    products = _write_products(
        tmp_path,
        [{"id": "zero", "price": 0}, {"id": "missing"}, {"id": "priced", "price": 5}],
    )

    with pytest.raises(CommandError) as error:
        call_command("import_catalog", products=products, stdout=StringIO())

    message = str(error.value)
    assert message.startswith("2 products without a valid price")
    assert "zero" in message and "missing" in message
    assert "priced\n" not in message


@pytest.mark.django_db
def test_dry_run_validates_and_reports_without_writing(tmp_path):
    products = _write_products(
        tmp_path,
        [{"id": "on", "price": 10}, {"id": "off", "price": 12, "active": False}],
    )
    out = StringIO()

    call_command("import_catalog", products=products, dry_run=True, stdout=out)

    assert not Product.objects.exists()
    assert not Application.objects.exists()
    output = out.getvalue()
    assert "Products to import: 2 (1 active, 1 inactive)" in output
    assert f"Applications to import: {len(_load('applications.json'))}" in output
    assert "Dry run: nothing was written." in output


@pytest.mark.django_db
def test_dry_run_still_rejects_unpriced_products(tmp_path):
    products = _write_products(tmp_path, [{"id": "unpriced", "price": 0}])

    with pytest.raises(CommandError, match="unpriced"):
        call_command("import_catalog", products=products, dry_run=True, stdout=StringIO())


@pytest.mark.django_db
def test_import_honors_active_flag_without_storing_it_in_data(tmp_path):
    # La exportación del panel trae `active` por producto: la columna lo toma y
    # `data` queda igual que la semilla, sin la clave.
    products = _write_products(
        tmp_path,
        [{"id": "on", "price": 10}, {"id": "off", "price": 12, "active": False}],
    )

    call_command("import_catalog", products=products, stdout=StringIO())

    assert Product.objects.get(pk="on").active is True
    inactive = Product.objects.get(pk="off")
    assert inactive.active is False
    assert inactive.data == {"id": "off", "price": 12}


@pytest.mark.django_db
def test_import_rejects_a_non_boolean_active_flag(tmp_path):
    products = _write_products(tmp_path, [{"id": "weird", "price": 10, "active": "no"}])

    with pytest.raises(CommandError, match="weird"):
        call_command("import_catalog", products=products, stdout=StringIO())

    assert not Product.objects.exists()


@pytest.mark.django_db
def test_if_empty_loads_the_seed_into_an_empty_database():
    out = StringIO()
    call_command("import_catalog", if_empty=True, stdout=out)

    assert Product.objects.count() == len(_load("products.json"))


@pytest.mark.django_db
def test_if_empty_skips_when_products_already_exist():
    Product.objects.create(id="panel-product", data={"title": "Edited"}, active=True)
    out = StringIO()

    call_command("import_catalog", if_empty=True, stdout=out)

    assert Product.objects.count() == 1
    assert "skipped" in out.getvalue()
