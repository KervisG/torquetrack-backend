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
