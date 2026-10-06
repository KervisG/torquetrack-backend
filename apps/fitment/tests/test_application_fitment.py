"""Fitment por aplicaciones: `check_product_fitment(..., applications)` y
`POST /api/fitment/check/` con filas de `ProductFitment`. Sin proveedores.

Con filas, el vehículo tiene que caer en alguna aplicación del producto (por
`applicationId` exacto o por año, marca y cilindrada) y, además, en el rango de
años propio del producto. Sin filas se usa el texto de siempre."""
import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Application, Product
from apps.fitment.services import applications_by_product, check_product_fitment

FORD_73_EARLY = {"id": "ford-73-powerstroke-1994-1997", "make": "Ford", "yearFrom": 1994,
                 "yearTo": 1997, "engine": "7.3", "models": ["F-250", "F-350"]}
FORD_60 = {"id": "ford-60-powerstroke-2003-2004", "make": "Ford", "yearFrom": 2003,
           "yearTo": 2004, "engine": "6.0", "models": ["F-250"]}
RAM_67 = {"id": "ram-67-cummins-2019-2024", "make": "RAM", "yearFrom": 2019,
          "yearTo": 2024, "engine": "6.7", "models": ["2500"]}

# El texto del producto dice 1994-2003 7.3: sin filas, un 2003 6.0 fallaría
# por motor y un 1999 7.3 pasaría. Las filas dicen solo 1994-1997.
PRODUCT = {"make": "Ford", "yearFrom": 1994, "yearTo": 2003, "engine": "7.3"}


def test_vehicle_inside_a_listed_application_is_compatible():
    result = check_product_fitment(
        PRODUCT, {"make": "Ford", "year": 1996, "engine": "7.3"}, [FORD_73_EARLY]
    )

    assert result == {"compatible": True, "reasons": [], "warnings": []}


def test_vehicle_outside_every_listed_application_is_not_compatible():
    result = check_product_fitment(
        PRODUCT, {"make": "Ford", "year": 1999, "engine": "7.3", "model": "F-250"},
        [FORD_73_EARLY],
    )

    assert result["compatible"] is False
    assert result["reasons"] == [
        "vehicle 1999 Ford F-250 7.3 is not a listed application for this product"
    ]


def test_product_year_range_still_applies_inside_an_application():
    product = {**PRODUCT, "yearFrom": 1996, "yearTo": 1997}

    result = check_product_fitment(product, {"make": "Ford", "year": 1995}, [FORD_73_EARLY])

    assert result["compatible"] is False
    assert result["reasons"] == ["year 1995 is outside 1996-1997"]


def test_application_id_from_the_garage_is_matched_exactly():
    listed = check_product_fitment(
        PRODUCT, {"applicationId": "ford-73-powerstroke-1994-1997", "year": 1995},
        [FORD_73_EARLY],
    )
    other = check_product_fitment(
        PRODUCT, {"applicationId": "ford-60-powerstroke-2003-2004", "year": 2003},
        [FORD_73_EARLY],
    )

    assert listed["compatible"] is True
    assert other["compatible"] is False
    assert other["reasons"] == [
        "vehicle application ford-60-powerstroke-2003-2004 is not listed for this product"
    ]


def test_ram_application_matches_a_dodge_vin():
    result = check_product_fitment({}, {"make": "Dodge", "year": 2020, "engine": "6.7"}, [RAM_67])

    assert result["compatible"] is True


def test_missing_engine_is_a_warning_not_a_reason():
    result = check_product_fitment(PRODUCT, {"make": "Ford", "year": 1996}, [FORD_73_EARLY])

    assert result["compatible"] is True
    assert result["warnings"] == [
        "VIN decoder did not return engine displacement; verify 7.3 manually before ordering"
    ]


def test_empty_vehicle_is_compatible_like_the_text_check():
    assert check_product_fitment(PRODUCT, {}, [FORD_73_EARLY])["compatible"] is True


def test_without_applications_falls_back_to_the_text_check():
    vehicle = {"make": "Ford", "year": 1999, "engine": "7.3"}

    assert check_product_fitment(PRODUCT, vehicle, [])["compatible"] is True
    assert check_product_fitment(PRODUCT, vehicle)["compatible"] is True


@pytest.mark.django_db
def test_applications_by_product_groups_the_relation_rows():
    early = Application.objects.create(data=FORD_73_EARLY)
    Application.objects.create(data=FORD_60)
    Product.objects.create(id="linked", data={}).applications.set([early])
    Product.objects.create(id="unlinked", data={})

    grouped = applications_by_product(["linked", "unlinked"])

    assert list(grouped) == ["linked"]
    assert grouped["linked"][0]["id"] == "ford-73-powerstroke-1994-1997"
    assert grouped["linked"][0]["yearTo"] == 1997


# --- POST /api/fitment/check/ -------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_throttle_cache(request):
    if "django_db" in request.keywords:
        from django.core.cache import cache

        cache.clear()


@pytest.mark.django_db
def test_check_endpoint_uses_fitment_rows_when_present():
    early = Application.objects.create(data=FORD_73_EARLY)
    Product.objects.create(
        id="ford-73-injector", data={"id": "ford-73-injector", "title": "Injector", **PRODUCT}
    ).applications.set([early])

    response = APIClient().post(
        "/api/fitment/check/",
        {"items": [{"id": "ford-73-injector"}],
         "vehicle": {"make": "Ford", "year": 1999, "engine": "7.3"}},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["compatible"] is False
    assert response.json()["results"][0]["reasons"] == [
        "vehicle 1999 Ford 7.3 is not a listed application for this product"
    ]
