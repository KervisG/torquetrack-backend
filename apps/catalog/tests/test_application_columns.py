"""Columnas tipadas de `Application`: marca, motor, años y modelos salen del
JSON y `data` devuelve la misma forma camelCase que consume la API."""

import pytest
from django.db import IntegrityError, transaction

from apps.catalog.models import Application

ROW = {
    "id": "ford-73-powerstroke-1994-1997",
    "vehicleType": "Pickup",
    "make": "Ford",
    "models": ["F-250", "F-350"],
    "yearFrom": 1994,
    "yearTo": 1997,
    "engine": "7.3",
    "engineCode": "T444E",
    "engineFamily": "Powerstroke",
    "fuelType": "Diesel",
    "vinCompatible": True,
    "serialCompatible": False,
}


@pytest.mark.django_db
def test_fitment_fields_are_stored_in_typed_columns():
    Application.objects.create(data=dict(ROW))

    application = Application.objects.get(code="ford-73-powerstroke-1994-1997")

    assert (application.make, application.vehicle_type) == ("Ford", "Pickup")
    assert application.vehicle_models == ["F-250", "F-350"]
    assert (application.year_from, application.year_to) == (1994, 1997)
    assert (application.engine, application.engine_code, application.engine_family) == (
        "7.3",
        "T444E",
        "Powerstroke",
    )
    assert application.fuel_type == "Diesel"
    assert (application.vin_compatible, application.serial_compatible) == (True, False)
    assert application.attributes == {"id": "ford-73-powerstroke-1994-1997"}


@pytest.mark.django_db
def test_data_rebuilds_the_api_shape():
    Application.objects.create(data=dict(ROW))

    assert Application.objects.get(code=ROW["id"]).data == ROW


@pytest.mark.django_db
def test_bulk_create_with_data_writes_the_columns():
    Application.objects.bulk_create(
        [Application(code="a1", data={"make": "RAM", "yearFrom": 2003})]
    )

    application = Application.objects.get(code="a1")
    assert (application.make, application.year_from) == ("RAM", 2003)


@pytest.mark.django_db
def test_applications_can_be_filtered_by_make_year_and_model_in_sql():
    Application.objects.create(data=dict(ROW))
    Application.objects.create(data={**ROW, "id": "ram", "make": "RAM", "models": ["2500"]})

    found = Application.objects.filter(
        make="Ford", year_from__lte=1995, year_to__gte=1995, vehicle_models__contains=["F-250"]
    )

    assert [application.code for application in found] == [ROW["id"]]


@pytest.mark.django_db
def test_the_database_rejects_a_year_range_that_ends_before_it_starts():
    with pytest.raises(IntegrityError), transaction.atomic():
        Application.objects.create(data={"id": "bad", "yearFrom": 2005, "yearTo": 2001})


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field, value", [("yearFrom", "soon"), ("vinCompatible", "yes"), ("models", "F-250")]
)
def test_a_value_of_the_wrong_type_is_rejected_before_saving(field, value):
    with pytest.raises(ValueError, match=field):
        Application.objects.create(data={"id": "bad", field: value})
