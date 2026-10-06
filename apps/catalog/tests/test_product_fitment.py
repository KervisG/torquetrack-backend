"""Relación normalizada producto ↔ aplicación (`ProductFitment`, tabla
`product_fitments`) y su backfill desde `data` (`backfill_product_fitments` y
`manage.py backfill_product_fitment`). Sin proveedores que mockear.

El backfill no adivina: `applicationIds` del producto manda; solo sin ellos se
cruza el texto (marca, rango de años y cilindrada con decimal) contra las
aplicaciones, y lo que no se puede leer o no cruza con ninguna queda reportado
sin filas."""
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction

from apps.catalog.models import Application, Product, ProductFitment
from apps.catalog.services import backfill_product_fitments

FORD_73_EARLY = {
    "id": "ford-73-powerstroke-1994-1997",
    "make": "Ford",
    "models": ["F-250", "F-350"],
    "yearFrom": 1994,
    "yearTo": 1997,
    "engine": "7.3",
}
FORD_73_LATE = {**FORD_73_EARLY, "id": "ford-73-powerstroke-1998-2003", "yearFrom": 1998,
                "yearTo": 2003}
FORD_60 = {**FORD_73_EARLY, "id": "ford-60-powerstroke-2003-2004", "yearFrom": 2003,
           "yearTo": 2004, "engine": "6.0"}
CHEVY_65 = {"id": "chevrolet-65-turbodiesel-1994-2000", "make": "Chevrolet",
            "models": ["C2500"], "yearFrom": 1994, "yearTo": 2000, "engine": "6.5"}
GMC_65 = {**CHEVY_65, "id": "gmc-65-turbodiesel-1994-2000", "make": "GMC"}


def _insert_applications(*rows):
    return [Application.objects.create(data=row) for row in rows]


def _insert_product(product_id, **data):
    return Product.objects.create(id=product_id, data={"id": product_id, **data})


def _codes(product_id):
    return sorted(
        ProductFitment.objects.filter(product_id=product_id).values_list(
            "application__code", flat=True
        )
    )


# --- modelo -----------------------------------------------------------------


@pytest.mark.django_db
def test_application_code_comes_from_data_id():
    (application,) = _insert_applications(FORD_73_EARLY)

    assert application.code == "ford-73-powerstroke-1994-1997"


@pytest.mark.django_db
def test_application_without_data_id_still_gets_a_unique_code():
    first = Application.objects.create(data={"make": "Ford"})
    second = Application.objects.create(data={"make": "Ford"})

    assert first.code and second.code
    assert first.code != second.code


@pytest.mark.django_db
def test_product_applications_relation_round_trips():
    early, late = _insert_applications(FORD_73_EARLY, FORD_73_LATE)
    product = _insert_product("ford-73-injector")

    product.applications.set([early, late])

    assert _codes("ford-73-injector") == [
        "ford-73-powerstroke-1994-1997",
        "ford-73-powerstroke-1998-2003",
    ]
    assert list(early.products.all()) == [product]


@pytest.mark.django_db
def test_same_product_and_application_cannot_repeat():
    (application,) = _insert_applications(FORD_73_EARLY)
    product = _insert_product("ford-73-injector")
    ProductFitment.objects.create(product=product, application=application)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProductFitment.objects.create(product=product, application=application)


@pytest.mark.django_db
def test_deleting_an_application_removes_its_fitment_rows_only():
    early, late = _insert_applications(FORD_73_EARLY, FORD_73_LATE)
    product = _insert_product("ford-73-injector")
    product.applications.set([early, late])

    early.delete()

    assert _codes("ford-73-injector") == ["ford-73-powerstroke-1998-2003"]
    assert Product.objects.filter(pk="ford-73-injector").exists()


# --- backfill ---------------------------------------------------------------


@pytest.mark.django_db
def test_backfill_links_explicit_application_ids():
    _insert_applications(CHEVY_65, GMC_65, FORD_73_EARLY)
    _insert_product(
        "gm-65-pump",
        make="Ford",  # el texto contradice: los ids explícitos mandan
        applicationIds=["chevrolet-65-turbodiesel-1994-2000", "gmc-65-turbodiesel-1994-2000"],
    )

    report = backfill_product_fitments(Product.objects.all())

    assert _codes("gm-65-pump") == [
        "chevrolet-65-turbodiesel-1994-2000",
        "gmc-65-turbodiesel-1994-2000",
    ]
    assert report["linkedFromIds"] == 1
    assert report["links"] == 2


@pytest.mark.django_db
def test_backfill_reports_unknown_ids_and_links_the_known_ones():
    _insert_applications(CHEVY_65)
    _insert_product(
        "gm-65-pump",
        applicationIds=["chevrolet-65-turbodiesel-1994-2000", "missing-application"],
    )
    _insert_product("only-unknown", applicationIds=["missing-application"], make="Ford",
                    yearFrom=1994, yearTo=1997, engine="7.3")

    report = backfill_product_fitments(Product.objects.all())

    assert _codes("gm-65-pump") == ["chevrolet-65-turbodiesel-1994-2000"]
    # Ids explícitos que no existen no caen al texto: sería adivinar.
    assert _codes("only-unknown") == []
    assert report["unknownApplicationIds"] == {
        "gm-65-pump": ["missing-application"],
        "only-unknown": ["missing-application"],
    }
    assert report["unresolved"] == ["only-unknown"]


@pytest.mark.django_db
def test_backfill_from_text_matches_make_years_and_displacement():
    _insert_applications(FORD_73_EARLY, FORD_73_LATE, FORD_60, CHEVY_65, GMC_65)
    _insert_product("ford-73-injector", make="Ford", yearFrom=1996, yearTo=1999,
                    engine="7.3", applicationIds=[])
    _insert_product("gm-65-pump", make="Chevrolet / GMC", yearFrom=1994, yearTo=2000,
                    engineFamily="6.5L Turbo Diesel")

    report = backfill_product_fitments(Product.objects.all())

    assert _codes("ford-73-injector") == [
        "ford-73-powerstroke-1994-1997",
        "ford-73-powerstroke-1998-2003",
    ]
    assert _codes("gm-65-pump") == [
        "chevrolet-65-turbodiesel-1994-2000",
        "gmc-65-turbodiesel-1994-2000",
    ]
    assert report["linkedFromText"] == 2
    assert report["links"] == 4


@pytest.mark.django_db
def test_backfill_reports_unparseable_unmatched_and_empty_products():
    _insert_applications(FORD_73_EARLY)
    _insert_product("no-years", make="Ford", engine="7.3")
    _insert_product("no-displacement", make="Ford", yearFrom=1994, yearTo=1997,
                    engine="Power Stroke")
    _insert_product("no-match", make="Ford", yearFrom=2017, yearTo=2019, engine="6.7")
    _insert_product("no-data", title="Shop rag")

    report = backfill_product_fitments(Product.objects.all())

    assert ProductFitment.objects.count() == 0
    assert report["scanned"] == 4
    assert report["unparseable"] == ["no-displacement", "no-years"]
    assert report["unmatched"] == ["no-match"]
    assert report["noData"] == 1


@pytest.mark.django_db
def test_backfill_keeps_existing_rows_unless_replace():
    early, late = _insert_applications(FORD_73_EARLY, FORD_73_LATE)
    product = _insert_product("ford-73-injector", applicationIds=["ford-73-powerstroke-1998-2003"])
    product.applications.set([early])

    kept = backfill_product_fitments(Product.objects.all())
    assert kept["skippedExisting"] == 1
    assert _codes("ford-73-injector") == ["ford-73-powerstroke-1994-1997"]

    replaced = backfill_product_fitments(Product.objects.all(), replace=True)
    assert replaced["linkedFromIds"] == 1
    assert _codes("ford-73-injector") == ["ford-73-powerstroke-1998-2003"]


@pytest.mark.django_db
def test_backfill_never_edits_product_data():
    _insert_applications(FORD_73_EARLY)
    product = _insert_product("ford-73-injector", applicationIds=["ford-73-powerstroke-1994-1997"])
    before = dict(product.data)

    backfill_product_fitments(Product.objects.all())

    product.refresh_from_db()
    assert product.data == before


# --- comando ----------------------------------------------------------------


@pytest.mark.django_db
def test_command_prints_the_report():
    _insert_applications(FORD_73_EARLY)
    _insert_product("ford-73-injector", applicationIds=["ford-73-powerstroke-1994-1997"])
    _insert_product("no-years", make="Ford", engine="7.3")
    out = StringIO()

    call_command("backfill_product_fitment", stdout=out)

    output = out.getvalue()
    assert "Products scanned: 2" in output
    assert "Linked from applicationIds: 1" in output
    assert "Unparseable: 1 (no-years)" in output
    assert _codes("ford-73-injector") == ["ford-73-powerstroke-1994-1997"]


@pytest.mark.django_db
def test_command_dry_run_writes_nothing():
    _insert_applications(FORD_73_EARLY)
    _insert_product("ford-73-injector", applicationIds=["ford-73-powerstroke-1994-1997"])
    out = StringIO()

    call_command("backfill_product_fitment", "--dry-run", stdout=out)

    assert "Linked from applicationIds: 1" in out.getvalue()
    assert "Dry run: no changes were saved." in out.getvalue()
    assert ProductFitment.objects.count() == 0
