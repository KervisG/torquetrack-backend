"""`catalog/0003_product_columns` mueve los campos de negocio de `data` a
columnas sin perder nada: lo que no entra se queda en `attributes`."""
from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("catalog", "0002_db_on_delete")]
AFTER = [("catalog", "0003_product_columns")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def migrate_products(transactional_db):
    def run(rows):
        old_apps = _migrate(BEFORE)
        Product = old_apps.get_model("catalog", "Product")
        for product_id, data in rows.items():
            Product.objects.create(id=product_id, slug=product_id, data=data)
        new_apps = _migrate(AFTER)
        return new_apps.get_model("catalog", "Product")

    yield run
    _migrate([("catalog", "0003_product_columns")])


def test_business_fields_move_to_columns(migrate_products):
    Product = migrate_products(
        {
            "p1": {
                "title": "Pump",
                "partNumber": "502-550",
                "price": 189.99,
                "coreCharge": 150,
                "stock": "Supplier Check",
                "yearFrom": 1994,
                "yearTo": 2000,
                "manufacturer": "Dorman",
            }
        }
    )

    product = Product.objects.get(pk="p1")
    assert (product.title, product.part_number) == ("Pump", "502-550")
    assert (product.price, product.core_charge) == (Decimal("189.99"), Decimal("150.00"))
    assert product.stock == "Supplier Check"
    assert (product.year_from, product.year_to) == (1994, 2000)
    assert product.attributes == {"manufacturer": "Dorman"}


def test_values_that_do_not_fit_stay_in_attributes(migrate_products):
    Product = migrate_products(
        {"p1": {"price": "call us", "coreCharge": -5, "yearFrom": 2005, "yearTo": 2001}}
    )

    product = Product.objects.get(pk="p1")
    assert (product.price, product.core_charge, product.year_from, product.year_to) == (
        None,
        None,
        None,
        None,
    )
    assert product.attributes == {
        "price": "call us",
        "coreCharge": -5,
        "yearFrom": 2005,
        "yearTo": 2001,
    }


def test_empty_values_are_dropped(migrate_products):
    Product = migrate_products({"p1": {"title": "", "price": None, "make": "Ford"}})

    product = Product.objects.get(pk="p1")
    assert (product.title, product.price, product.make) == (None, None, "Ford")
    assert product.attributes == {}
