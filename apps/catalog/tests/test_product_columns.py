"""Columnas tipadas de `Product`: los campos de negocio salen de `data` y
`data` devuelve la misma forma camelCase que consume la API."""
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.catalog.models import Product

CATALOG_ROW = {
    "id": "gm-65-pump",
    "title": "6.5L Fuel Injection Pump",
    "partNumber": "502-550",
    "price": 189.99,
    "compareAt": 249,
    "coreCharge": 150,
    "purchaseCost": 120.5,
    "stock": "Supplier Check",
    "make": "Chevrolet / GMC",
    "model": "C/K 2500 / 3500",
    "category": "Injection Pump",
    "yearFrom": 1994,
    "yearTo": 2000,
    "manufacturer": "Dorman",
    "description": "Remanufactured pump.",
}


@pytest.mark.django_db
def test_business_fields_are_stored_in_typed_columns():
    Product.objects.create(id="gm-65-pump", data=dict(CATALOG_ROW))

    product = Product.objects.get(pk="gm-65-pump")

    assert product.title == "6.5L Fuel Injection Pump"
    assert product.part_number == "502-550"
    assert product.price == Decimal("189.99")
    assert product.compare_at == Decimal("249.00")
    assert product.core_charge == Decimal("150.00")
    assert product.purchase_cost == Decimal("120.50")
    assert product.stock == "Supplier Check"
    assert (product.make, product.model, product.category) == (
        "Chevrolet / GMC",
        "C/K 2500 / 3500",
        "Injection Pump",
    )
    assert (product.year_from, product.year_to) == (1994, 2000)


@pytest.mark.django_db
def test_attributes_keep_only_the_fields_without_a_column():
    Product.objects.create(id="gm-65-pump", data=dict(CATALOG_ROW))

    product = Product.objects.get(pk="gm-65-pump")

    assert product.attributes == {
        "id": "gm-65-pump",
        "manufacturer": "Dorman",
        "description": "Remanufactured pump.",
    }


@pytest.mark.django_db
def test_data_rebuilds_the_api_shape():
    Product.objects.create(id="gm-65-pump", data=dict(CATALOG_ROW))

    assert Product.objects.get(pk="gm-65-pump").data == CATALOG_ROW


@pytest.mark.django_db
def test_data_omits_fields_without_a_value():
    Product.objects.create(id="bare", data={"title": "Bare"})

    assert Product.objects.get(pk="bare").data == {"title": "Bare"}


@pytest.mark.django_db
def test_update_or_create_with_data_defaults_writes_the_columns():
    Product.objects.create(id="gm-65-pump", data={"title": "Old", "price": 10})

    Product.objects.update_or_create(
        id="gm-65-pump", defaults={"data": {"title": "New", "price": 20}}
    )

    product = Product.objects.get(pk="gm-65-pump")
    assert (product.title, product.price) == ("New", Decimal("20.00"))


@pytest.mark.django_db
def test_assigning_data_to_a_loaded_product_replaces_the_columns():
    Product.objects.create(id="gm-65-pump", data=dict(CATALOG_ROW))
    product = Product.objects.get(pk="gm-65-pump")

    product.data = {"title": "Renamed", "price": 5}
    product.save()

    stored = Product.objects.get(pk="gm-65-pump")
    assert stored.data == {"title": "Renamed", "price": 5.0}


@pytest.mark.django_db
def test_saving_a_loaded_product_keeps_its_columns():
    Product.objects.create(id="gm-65-pump", data=dict(CATALOG_ROW))
    product = Product.objects.get(pk="gm-65-pump")

    product.active = False
    product.save()

    assert Product.objects.get(pk="gm-65-pump").data == CATALOG_ROW


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field, value",
    [("price", -1), ("compareAt", -1), ("coreCharge", -1), ("purchaseCost", -1)],
)
def test_the_database_rejects_negative_money(field, value):
    with pytest.raises(IntegrityError), transaction.atomic():
        Product.objects.create(id="neg", data={"title": "Neg", field: value})


@pytest.mark.django_db
def test_the_database_rejects_a_year_range_that_ends_before_it_starts():
    with pytest.raises(IntegrityError), transaction.atomic():
        Product.objects.create(id="years", data={"yearFrom": 2005, "yearTo": 2001})


@pytest.mark.django_db
def test_a_non_numeric_money_value_is_rejected_before_saving():
    with pytest.raises(ValueError, match="price"):
        Product.objects.create(id="bad", data={"price": "abc"})
