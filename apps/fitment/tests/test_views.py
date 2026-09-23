"""Tests de `POST /api/fitment/check`."""

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Product

PRODUCT_DATA = {
    "id": "ford-73-injector-alliant-ap63992",
    "title": "7.3L Powerstroke Fuel Injector",
    "partNumber": "AP63992",
    "make": "Ford",
    "yearFrom": 1994,
    "yearTo": 1997,
    "engineFamily": "7.3",
}


def _insert_product(product_id, data, active=True):
    Product.objects.create(id=product_id, data=data, active=active)


@pytest.mark.django_db
def test_missing_vehicle_returns_400():
    response = APIClient().post(
        "/api/fitment/check/", {"items": [{"id": "x"}]}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Vehicle required"


@pytest.mark.django_db
def test_empty_items_returns_cart_is_empty():
    response = APIClient().post(
        "/api/fitment/check/",
        {"vehicle": {"make": "Ford", "year": 1996}, "items": []},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Cart is empty"


@pytest.mark.django_db
def test_batch_match_returns_per_product_result():
    _insert_product("ford-73-injector-alliant-ap63992", PRODUCT_DATA, active=True)

    response = APIClient().post(
        "/api/fitment/check/",
        {
            "vehicle": {"make": "Ford", "year": 1996, "engine": "7.3"},
            "items": [{"id": "ford-73-injector-alliant-ap63992"}],
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["compatible"] is True
    assert body["results"] == [
        {
            "id": "ford-73-injector-alliant-ap63992",
            "title": "7.3L Powerstroke Fuel Injector",
            "partNumber": "AP63992",
            "compatible": True,
            "reasons": [],
            "warnings": [],
        }
    ]


@pytest.mark.django_db
def test_inactive_product_is_silently_excluded_from_results():
    _insert_product("ford-73-injector-alliant-ap63992", PRODUCT_DATA, active=False)

    response = APIClient().post(
        "/api/fitment/check/",
        {
            "vehicle": {"make": "Ford", "year": 1996},
            "items": [{"id": "ford-73-injector-alliant-ap63992"}],
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    # Comportamiento intencional del contrato: `all([])` es verdadero, así
    # que una lista de resultados vacía se reporta como compatible.
    assert body == {"compatible": True, "results": []}


@pytest.mark.django_db
def test_productid_key_is_also_accepted():
    _insert_product("ford-73-injector-alliant-ap63992", PRODUCT_DATA, active=True)

    response = APIClient().post(
        "/api/fitment/check/",
        {
            "vehicle": {"make": "Ford", "year": 1996},
            "items": [{"productId": "ford-73-injector-alliant-ap63992"}],
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["id"] == "ford-73-injector-alliant-ap63992"
