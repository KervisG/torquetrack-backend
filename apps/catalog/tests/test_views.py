
import pytest
from rest_framework.test import APIClient

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
    "purchaseCost": 90.5,
    "supplierCost": 85.0,
    "internalNotes": "reorder from Dorman rep",
    "supplierSku": "DORM-502550",
    "supplierEmail": "sales@dorman-supplier.example",
    "supplierPhone": "555-0100",
    "supplier": "Dorman / Authorized Distributor",
    "supplierPartNumber": "DORM-502550-A",
    "supplierUrl": "https://supplier.example/502-550",
    "cost": 88.0,
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

RESTRICTED_FIELDS = [
    "purchaseCost",
    "supplierCost",
    "internalNotes",
    "supplierSku",
    "supplierEmail",
    "supplierPhone",
    "supplier",
    "supplierPartNumber",
    "supplierUrl",
    "cost",
]


def _insert_product(product_id, data, active=True):
    Product.objects.create(id=product_id, data=data, active=active)


def _insert_application(data):
    return Application.objects.create(data=data).pk


@pytest.mark.django_db
def test_product_list_strips_internal_cost_fields():
    _insert_product("gm-65-injection-pump-dorman-502550", REAL_PRODUCT_SHAPE, active=True)

    response = APIClient().get("/api/products/")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 1
    for field in RESTRICTED_FIELDS:
        assert field not in body[0]
    assert body[0]["title"] == "6.5L Turbo Diesel Fuel Injection Pump"
    assert body[0]["manufacturer"] == "Dorman"


@pytest.mark.django_db
def test_product_list_excludes_inactive_products():
    _insert_product("discontinued-part", {"title": "Discontinued"}, active=False)
    _insert_product("gm-65-injection-pump-dorman-502550", REAL_PRODUCT_SHAPE, active=True)

    response = APIClient().get("/api/products/")

    body = response.json()
    assert [p["id"] for p in body] == ["gm-65-injection-pump-dorman-502550"]


@pytest.mark.django_db
def test_product_detail_strips_internal_cost_fields():
    _insert_product("gm-65-injection-pump-dorman-502550", REAL_PRODUCT_SHAPE, active=True)

    response = APIClient().get("/api/products/gm-65-injection-pump-dorman-502550/")

    assert response.status_code == 200
    body = response.json()
    for field in RESTRICTED_FIELDS:
        assert field not in body
    assert body["id"] == "gm-65-injection-pump-dorman-502550"


@pytest.mark.django_db
def test_product_detail_404_for_inactive_product():
    _insert_product("discontinued-part", {"title": "Discontinued"}, active=False)

    response = APIClient().get("/api/products/discontinued-part/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_application_list_returns_full_data_unfiltered():
    _insert_application(REAL_APPLICATION_SHAPE)

    response = APIClient().get("/api/applications/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "ford-73-powerstroke-1994-1997"
    assert body[0]["models"] == ["F-250", "F-350"]


@pytest.mark.django_db
def test_application_detail_returns_full_data():
    application_pk = _insert_application(REAL_APPLICATION_SHAPE)

    response = APIClient().get(f"/api/applications/{application_pk}/")

    assert response.status_code == 200
    assert response.json()["make"] == "Ford"


# --- slug -------------------------------------------------------------------


@pytest.mark.django_db
def test_product_list_and_detail_expose_the_slug():
    _insert_product("gm-65-injection-pump-dorman-502550", REAL_PRODUCT_SHAPE, active=True)

    listed = APIClient().get("/api/products/").json()[0]
    detail = APIClient().get("/api/products/gm-65-injection-pump-dorman-502550/").json()

    assert listed["slug"] == "65l-turbo-diesel-fuel-injection-pump-502-550"
    assert detail["slug"] == listed["slug"]


@pytest.mark.django_db
def test_product_detail_resolves_by_slug():
    _insert_product("gm-65-injection-pump-dorman-502550", REAL_PRODUCT_SHAPE, active=True)

    response = APIClient().get("/api/products/65l-turbo-diesel-fuel-injection-pump-502-550/")

    assert response.status_code == 200
    assert response.json()["id"] == "gm-65-injection-pump-dorman-502550"


@pytest.mark.django_db
def test_product_detail_by_slug_404_for_inactive_product():
    _insert_product("discontinued-part", {"title": "Old Pump", "partNumber": "OP1"}, active=False)

    response = APIClient().get("/api/products/old-pump-op1/")

    assert response.status_code == 404
    assert "error" in response.json()


@pytest.mark.django_db
def test_product_detail_prefers_the_id_over_another_products_slug():
    # El id siempre gana: un slug que coincide con el id de otro producto no
    # puede secuestrar la URL vieja por id.
    _insert_product("pump-a", {"title": "Pump", "partNumber": "B"}, active=True)
    Product.objects.create(id="other", data={"title": "Other"}, active=True, slug="pump-a")

    response = APIClient().get("/api/products/pump-a/")

    assert response.json()["title"] == "Pump"


@pytest.mark.django_db
def test_product_payload_slug_comes_from_the_column_not_from_data():
    _insert_product("p1", {"title": "Pump", "partNumber": "A", "slug": "spoofed"}, active=True)

    assert APIClient().get("/api/products/p1/").json()["slug"] == "pump-a"
