"""Stage A binding tests for `products` and `applications` (design decision
#3). Fixture jsonb shapes mirror real production rows from `data/products.json`
and `data/applications.json` (the Next.js fallback fixtures), not invented
shapes, so this proves compatibility with real data, not just any JSON.
"""
import json

import pytest
from django.db import connection

from apps.catalog.models import Application, Product

REAL_PRODUCT_SHAPE = {
    "vehicleType": "Pickup",
    "make": "Chevrolet / GMC",
    "model": "C/K 2500 / 3500",
    "yearFrom": 1994,
    "yearTo": 2000,
    "engine": "6.5",
    "fuelType": "Diesel",
    "manufacturer": "Dorman",
    "partNumber": "502-550",
    "price": 189.99,
    "id": "gm-65-injection-pump-dorman-502550",
    "title": "6.5L Turbo Diesel Fuel Injection Pump",
}

REAL_APPLICATION_SHAPE = {
    "id": "ford-73-powerstroke-1994-1997",
    "vehicleType": "Pickup",
    "make": "Ford",
    "models": ["F-250", "F-350"],
    "yearFrom": 1994,
    "yearTo": 1997,
    "engine": "7.3",
    "vinCompatible": True,
    "serialCompatible": True,
}


def _insert_product(product_id, data, active=True):
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into products (id, data, active) values (%s, %s, %s)",
            [product_id, json.dumps(data), active],
        )


def _insert_application(data):
    # `applications.id` is `bigserial` (schema.sql), NOT the business
    # identifier carried inside `data["id"]` — the DB generates the real
    # primary key, so it must never be supplied explicitly here.
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into applications (data) values (%s) returning id",
            [json.dumps(data)],
        )
        return cursor.fetchone()[0]


@pytest.mark.django_db
def test_reads_active_product_with_real_production_shape():
    _insert_product("gm-65-injection-pump-dorman-502550", REAL_PRODUCT_SHAPE, active=True)

    product = Product.objects.get(pk="gm-65-injection-pump-dorman-502550")

    assert product.active is True
    assert product.data["title"] == "6.5L Turbo Diesel Fuel Injection Pump"
    assert product.data["manufacturer"] == "Dorman"


@pytest.mark.django_db
def test_inactive_product_is_excluded_by_active_filter():
    _insert_product("discontinued-part", {"title": "Discontinued Part"}, active=False)
    _insert_product("gm-65-injection-pump-dorman-502550", REAL_PRODUCT_SHAPE, active=True)

    active_ids = list(
        Product.objects.filter(active=True).order_by("id").values_list("id", flat=True)
    )

    assert active_ids == ["gm-65-injection-pump-dorman-502550"]


@pytest.mark.django_db
def test_reads_application_with_multi_model_shape():
    application_pk = _insert_application(REAL_APPLICATION_SHAPE)

    application = Application.objects.get(pk=application_pk)

    assert application.data["id"] == "ford-73-powerstroke-1994-1997"
    assert application.data["models"] == ["F-250", "F-350"]
    assert application.data["make"] == "Ford"
