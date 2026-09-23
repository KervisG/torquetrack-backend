"""`POST /api/fitment/check/`. Sin proveedores: solo lee `Product`.

Un producto inexistente o inactivo no es compatible: nunca puede pasar el
chequeo previo al pago.
"""
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


def _unavailable(product_id):
    return {
        "id": product_id,
        "title": "",
        "partNumber": "",
        "compatible": False,
        "reasons": ["product is not available"],
        "warnings": [],
    }


@pytest.mark.django_db
@pytest.mark.parametrize("active", [False, None], ids=["inactive", "unknown"])
def test_inactive_or_unknown_product_is_not_compatible(active):
    if active is not None:
        _insert_product("ford-73-injector-alliant-ap63992", PRODUCT_DATA, active=active)

    response = APIClient().post(
        "/api/fitment/check/",
        {
            "vehicle": {"make": "Ford", "year": 1996},
            "items": [{"id": "ford-73-injector-alliant-ap63992"}],
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json() == {
        "compatible": False,
        "results": [_unavailable("ford-73-injector-alliant-ap63992")],
    }


@pytest.mark.django_db
def test_one_unknown_product_makes_the_cart_incompatible():
    _insert_product("ford-73-injector-alliant-ap63992", PRODUCT_DATA, active=True)

    response = APIClient().post(
        "/api/fitment/check/",
        {
            "vehicle": {"make": "Ford", "year": 1996, "engine": "7.3"},
            "items": [{"id": "ford-73-injector-alliant-ap63992"}, {"id": "ghost-part"}],
        },
        format="json",
    )

    body = response.json()
    assert body["compatible"] is False
    assert [result["compatible"] for result in body["results"]] == [True, False]
    assert body["results"][1] == _unavailable("ghost-part")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "items",
    [[{}], [{"id": ""}], ["ford-73"], [None], "ford-73"],
    ids=["no-id", "blank-id", "string-item", "null-item", "not-a-list"],
)
def test_items_without_a_product_id_return_400(items):
    response = APIClient().post(
        "/api/fitment/check/",
        {"vehicle": {"make": "Ford", "year": 1996}, "items": items},
        format="json",
    )

    assert response.status_code == 400
    assert "error" in response.json()


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
