"""Tests del comando `import_catalog`, que carga el catálogo semilla de
`apps/catalog/data/` (`products.json` y `applications.json`).

Se corre contra los archivos reales del repositorio, no contra copias
reducidas: el test también protege que esos JSON sigan siendo importables.
"""

import json
from io import StringIO

import pytest
from django.core.management import call_command

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
