"""Las formas del JSON copian filas reales del catálogo semilla."""

import pytest

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
    Product.objects.create(id=product_id, data=data, active=active)


def _insert_application(data):
    # `applications.id` es un `BigAutoField`, no el identificador de negocio
    # que viaja en `data["id"]`: la base genera la clave primaria.
    return Application.objects.create(data=data).pk


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


# --- slug SEO -------------------------------------------------------------
# El slug se genera una sola vez, al crear el producto, desde el título y el
# número de parte: la URL pública (`/product/<slug>`) no cambia al editar.


@pytest.mark.django_db
def test_product_gets_a_slug_from_title_and_part_number_on_create():
    product = Product.objects.create(
        id="p1", data={"title": "Bosch CP3 Injection Pump", "partNumber": "0445020150"}
    )

    assert product.slug == "bosch-cp3-injection-pump-0445020150"
    assert Product.objects.get(pk="p1").slug == "bosch-cp3-injection-pump-0445020150"


@pytest.mark.django_db
def test_product_slug_does_not_repeat_a_part_number_already_in_the_title():
    product = Product.objects.create(
        id="p1", data={"title": "Dorman 502-550 Pump", "partNumber": "502-550"}
    )

    assert product.slug == "dorman-502-550-pump"


@pytest.mark.django_db
def test_product_slug_is_unique_with_a_numeric_suffix():
    data = {"title": "Lift Pump", "partNumber": "LP-1"}
    first = Product.objects.create(id="p1", data=data)
    second = Product.objects.create(id="p2", data=data)
    third = Product.objects.create(id="p3", data=data)

    assert [first.slug, second.slug, third.slug] == [
        "lift-pump-lp-1",
        "lift-pump-lp-1-2",
        "lift-pump-lp-1-3",
    ]


@pytest.mark.django_db
def test_product_slug_falls_back_to_the_id_without_title_or_part_number():
    product = Product.objects.create(id="GM_65_Pump", data={})

    assert product.slug == "gm_65_pump"


@pytest.mark.django_db
def test_product_slug_stays_stable_when_the_title_changes():
    product = Product.objects.create(id="p1", data={"title": "Old Title", "partNumber": "X1"})

    product.data = {"title": "Brand New Title", "partNumber": "X1"}
    product.save()

    assert Product.objects.get(pk="p1").slug == "old-title-x1"


@pytest.mark.django_db
def test_product_slug_is_bounded_in_length():
    product = Product.objects.create(id="p1", data={"title": "Very Long Title " * 30})

    assert len(product.slug) <= 120
    assert not product.slug.endswith("-")
