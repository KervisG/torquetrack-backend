"""Búsqueda, filtros y paginación de `GET /api/products/`: el servidor
devuelve una página y las opciones de los filtros; el navegador ya no baja
el catálogo entero."""

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Application, Product

URL = "/api/products/"


def _product(product_id, **data):
    active = data.pop("active", True)
    return Product.objects.create(
        id=product_id,
        data={"id": product_id, "title": product_id, "price": 100, **data},
        active=active,
    )


def _get(**params):
    response = APIClient().get(URL, params)
    assert response.status_code == 200
    return response.json()


def _ids(**params):
    return [row["id"] for row in _get(**params)["results"]]


# --- paginación -------------------------------------------------------------


@pytest.mark.django_db
def test_the_list_is_a_page_with_its_totals():
    for index in range(20):
        _product(f"p{index:02}")

    body = _get()

    assert (body["count"], body["page"], body["pageSize"], body["pageCount"]) == (20, 1, 16, 2)
    assert [row["id"] for row in body["results"]] == [f"p{index:02}" for index in range(16)]


@pytest.mark.django_db
def test_page_and_page_size_select_the_slice():
    for index in range(7):
        _product(f"p{index}")

    body = _get(page=2, pageSize=3)

    assert [row["id"] for row in body["results"]] == ["p3", "p4", "p5"]
    assert (body["page"], body["pageSize"], body["pageCount"]) == (2, 3, 3)


@pytest.mark.django_db
def test_a_page_past_the_end_falls_back_to_the_last_one():
    for index in range(5):
        _product(f"p{index}")

    body = _get(page=99, pageSize=2)

    assert body["page"] == 3
    assert [row["id"] for row in body["results"]] == ["p4"]


@pytest.mark.django_db
@pytest.mark.parametrize(("raw", "size"), [("500", 100), ("0", 16), ("abc", 16), ("-3", 16)])
def test_page_size_is_bounded(raw, size):
    _product("p1")

    assert _get(pageSize=raw)["pageSize"] == size


@pytest.mark.django_db
def test_inactive_products_and_internal_fields_stay_out():
    _product("on", purchaseCost=40, supplier="ACME")
    _product("off", active=False)

    (row,) = _get()["results"]

    assert row["id"] == "on"
    assert "purchaseCost" not in row and "supplier" not in row


# --- búsqueda ---------------------------------------------------------------


@pytest.mark.django_db
def test_q_searches_the_title_and_the_descriptive_fields():
    _product("pump", title="Fuel Injection Pump", oemPart="0445020150")
    _product("turbo", title="Turbocharger", engineFamily="Powerstroke")

    assert _ids(q="injection") == ["pump"]
    assert _ids(q="0445020150") == ["pump"]
    assert _ids(q="POWERSTROKE") == ["turbo"]
    assert _ids(q="nothing") == []


@pytest.mark.django_db
def test_q_finds_a_part_number_without_dashes_or_spaces():
    _product("pump", partNumber="502-550")
    _product("other", partNumber="999-111")

    assert _ids(q="502550") == ["pump"]
    assert _ids(q="502 550") == ["pump"]


@pytest.mark.django_db
def test_q_does_not_join_two_part_numbers_into_one():
    _product("pair", partNumber="AB12 / 34CD")

    assert _ids(q="1234") == []
    assert _ids(q="34cd") == ["pair"]


# --- filtros ----------------------------------------------------------------


@pytest.mark.django_db
def test_brand_matches_one_of_the_manufacturers_of_the_part():
    _product("both", manufacturer="Alliant Power / Bosch")
    _product("bosch", manufacturer="Bosch")
    _product("garrett", manufacturer="Garrett")

    assert _ids(brand="bosch") == ["bosch", "both"]
    assert _ids(brand="Alliant Power") == ["both"]
    assert _ids(brand="Alliant") == []


@pytest.mark.django_db
def test_category_matches_its_aliases():
    _product("a", category="Fuel Injectors")
    _product("b", category="Injector")
    _product("c", category="Turbocharger")

    assert _ids(category="INJECTOR") == ["a", "b"]
    assert _ids(category="Turbo") == ["c"]
    assert _ids(category="All") == ["a", "b", "c"]


@pytest.mark.django_db
def test_condition_is_matched_without_case():
    _product("new", condition="New")
    _product("reman", condition="Remanufactured")

    assert _ids(condition="new") == ["new"]


@pytest.mark.django_db
def test_price_range_accepts_what_the_buyer_types():
    _product("cheap", price=50)
    _product("mid", price=1000)
    _product("high", price=2500)

    assert _ids(min="100") == ["high", "mid"]
    assert _ids(max="$1,000") == ["cheap", "mid"]
    assert _ids(min="100", max="2000") == ["mid"]
    assert _ids(min="abc") == ["cheap", "high", "mid"]


@pytest.mark.django_db
def test_sort_orders_by_price():
    _product("b", price=300)
    _product("a", price=100)
    _product("c", price=200)

    assert _ids(sort="low") == ["a", "c", "b"]
    assert _ids(sort="high") == ["b", "c", "a"]
    assert _ids() == ["a", "b", "c"]


@pytest.mark.django_db
def test_ids_returns_those_products_without_facets():
    for product_id in ("a", "b", "c"):
        _product(product_id)

    body = _get(ids="c,a,missing")

    assert [row["id"] for row in body["results"]] == ["a", "c"]
    assert "facets" not in body


# --- vehículo ---------------------------------------------------------------


@pytest.fixture
def fitment(db):
    ford = Application.objects.create(
        data={"id": "ford-73", "make": "Ford", "yearFrom": 1994, "yearTo": 2003, "engine": "7.3"}
    )
    ram = Application.objects.create(
        data={"id": "ram-59", "make": "RAM", "yearFrom": 1998, "yearTo": 2007, "engine": "5.9"}
    )
    _product("ford-early", yearFrom=1994, yearTo=1997).applications.set([ford])
    _product("ford-late", yearFrom=1999, yearTo=2003).applications.set([ford])
    _product("ram", yearFrom=1998, yearTo=2007).applications.set([ram])
    # Sin filas de compatibilidad: se decide por el texto del producto.
    _product("ford-text", make="Ford", yearFrom=1994, yearTo=2003, engine="7.3L")


def test_an_application_keeps_the_products_listed_for_it(fitment):
    assert _ids(applicationId="ford-73") == ["ford-early", "ford-late", "ford-text"]


def test_the_vehicle_year_narrows_the_application(fitment):
    assert _ids(applicationId="ford-73", vehicleYear="1995") == ["ford-early", "ford-text"]


def test_a_vin_vehicle_is_matched_by_make_year_and_engine(fitment):
    params = {"vehicleMake": "FORD", "vehicleYear": "2001", "vehicleEngine": "7.3L V8"}

    assert _ids(**params) == ["ford-late", "ford-text"]


def test_a_dodge_vin_finds_ram_parts(fitment):
    assert _ids(vehicleMake="Dodge", vehicleYear="2004", vehicleEngine="5.9") == ["ram"]


# --- opciones de los filtros ------------------------------------------------


@pytest.mark.django_db
def test_facets_come_from_the_whole_catalog_not_from_the_page():
    _product(
        "a", manufacturer="Alliant Power / Bosch", category="Injector", condition="New", price=199.5
    )
    _product("b", manufacturer="Garrett", category="Turbo", condition="Remanufactured", price=2400)
    _product("off", manufacturer="Hidden", category="Hidden", price=9000, active=False)

    facets = _get(q="garrett", pageSize=1)["facets"]

    assert facets == {
        "brands": ["Alliant Power", "Bosch", "Garrett"],
        "categories": ["Injector", "Turbo"],
        "conditions": ["New", "Remanufactured"],
        "priceCeiling": 2400,
    }


# --- resumen para la portada ------------------------------------------------


@pytest.mark.django_db
def test_overview_groups_the_catalog_by_category_and_truck():
    _product("i1", category="Injector", manufacturer="Bosch", make="Ford")
    _product("i2", category="Fuel Injectors", manufacturer="Alliant Power / Bosch", make="Ford")
    _product("t1", category="Turbo", manufacturer="Garrett", make="RAM")
    _product("off", category="Turbo", manufacturer="Hidden", make="RAM", active=False)

    overview = _get(overview="1", pageSize=1)["overview"]

    assert overview == {
        "productCount": 3,
        "categories": [
            {
                "value": "INJECTOR",
                "label": "Fuel Injectors",
                "count": 2,
                "brands": ["Alliant Power", "Bosch"],
            },
            {"value": "TURBO", "label": "Turbo", "count": 1, "brands": ["Garrett"]},
        ],
        "makes": [{"name": "Ford", "count": 2}, {"name": "RAM", "count": 1}],
    }


@pytest.mark.django_db
def test_overview_is_only_sent_when_asked():
    _product("p1")

    assert "overview" not in _get()
