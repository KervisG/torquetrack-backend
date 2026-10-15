"""`import_tt_products`: crea la versión TorqueTrack de productos existentes
desde el Excel de números TT. El Excel se arma en `tmp_path` con openpyxl.
Sin proveedores que mockear."""
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.catalog.management.commands.import_tt_products import DATA_FILE, tt_title
from apps.catalog.models import Application, Brand, Product

openpyxl = pytest.importorskip("openpyxl")

HEADER = [
    "Número TT",
    "Marca",
    "Modelo",
    "Años",
    "Motor",
    "Código motor",
    "Categoría",
    "Título",
    "Cross reference OEM",
    "Cross reference Reman",
    "Cross reference Aftermarket",
    "ID original",
]


def _row(tt="TT-INJ-F67-01", original="ford-inj", **overrides):
    values = {
        "Número TT": tt,
        "Marca": "Ford",
        "Modelo": "F-250 / F-350",
        "Años": "2011-2014",
        "Motor": "6.7",
        "Código motor": "6.7L",
        "Categoría": "Injector",
        "Título": "6.7L Power Stroke Fuel Injector - Bosch",
        "Cross reference OEM": "BC3Z-9E527-B",
        "Cross reference Reman": "0 986 435 415",
        "Cross reference Aftermarket": None,
        "ID original": original,
        **overrides,
    }
    return [values[column] for column in HEADER]


def _workbook(tmp_path, rows, sheet="Numeros TT"):
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.append(HEADER)
    for row in rows:
        worksheet.append(row)
    path = tmp_path / "tt.xlsx"
    workbook.save(path)
    return path


def _original(product_id="ford-inj", **data):
    product = Product.objects.create(
        id=product_id,
        data={
            "id": product_id,
            "title": "6.7L Power Stroke Fuel Injector - Bosch",
            "partNumber": "0986435415",
            "manufacturer": "Bosch",
            "type": "Reman",
            "price": 300,
            "image": "https://cdn.test/inj.webp",
            "condition": "Remanufactured",
            **data,
        },
        active=True,
    )
    return product


def _run(path, **options):
    out = StringIO()
    call_command("import_tt_products", str(path), stdout=out, **options)
    return out.getvalue()


@pytest.mark.django_db
def test_creates_an_active_torquetrack_copy_of_the_original(tmp_path):
    original = _original()
    application = Application.objects.create(code="ford-67", data={"id": "ford-67"})
    original.applications.set([application])

    output = _run(_workbook(tmp_path, [_row()]))

    product = Product.objects.get(pk="tt-inj-f67-01")
    assert product.active is True
    data = product.data
    assert data["partNumber"] == "TT-INJ-F67-01"
    assert data["manufacturer"] == "TorqueTrack"
    assert data["title"] == "6.7L Power Stroke Fuel Injector - TorqueTrack"
    assert data["price"] == 1
    assert (data["yearFrom"], data["yearTo"]) == (2011, 2014)
    assert data["oemPart"] == "BC3Z-9E527-B"
    assert data["remanPart"] == "0 986 435 415"
    assert data["image"] == "https://cdn.test/inj.webp"
    assert data["condition"] == "Remanufactured"
    assert "type" not in data
    assert [app.code for app in product.applications.all()] == ["ford-67"]
    assert Brand.objects.filter(name="TorqueTrack").exists()
    assert "TorqueTrack products created: 1" in output
    # El original sigue igual: la tienda muestra los dos.
    original.refresh_from_db()
    assert (original.data["manufacturer"], original.data["price"]) == ("Bosch", 300)


@pytest.mark.django_db
def test_an_empty_cell_keeps_the_original_value(tmp_path):
    _original(engineCode="Power Stroke 6.7")

    _run(_workbook(tmp_path, [_row(**{"Código motor": None})]))

    assert Product.objects.get(pk="tt-inj-f67-01").data["engineCode"] == "Power Stroke 6.7"


@pytest.mark.django_db
def test_skips_torquetrack_products_that_already_exist(tmp_path):
    _original()
    Product.objects.create(
        id="tt-inj-f67-01", data={"title": "Priced", "price": 250}, active=True
    )

    output = _run(_workbook(tmp_path, [_row()]))

    assert Product.objects.get(pk="tt-inj-f67-01").data["price"] == 250
    assert "skipped 1 existing" in output


@pytest.mark.django_db
def test_a_missing_original_aborts_without_writing(tmp_path):
    _original()
    rows = [_row(), _row(tt="TT-INJ-F67-02", original="does-not-exist")]

    with pytest.raises(CommandError, match="does-not-exist"):
        _run(_workbook(tmp_path, rows))

    assert not Product.objects.filter(pk__startswith="tt-").exists()


@pytest.mark.django_db
def test_a_repeated_tt_number_aborts_without_writing(tmp_path):
    _original()

    with pytest.raises(CommandError, match="repeated"):
        _run(_workbook(tmp_path, [_row(), _row()]))

    assert not Product.objects.filter(pk__startswith="tt-").exists()


@pytest.mark.django_db
def test_dry_run_reports_without_writing(tmp_path):
    _original()

    output = _run(_workbook(tmp_path, [_row()]), dry_run=True)

    assert "TorqueTrack products to create: 1" in output
    assert not Product.objects.filter(pk__startswith="tt-").exists()


@pytest.mark.django_db
def test_rejects_a_file_without_the_tt_sheet(tmp_path):
    with pytest.raises(CommandError, match="Numeros TT"):
        _run(_workbook(tmp_path, [_row()], sheet="Sheet1"))


@pytest.mark.django_db
def test_reads_the_json_copy_saved_with_to_json(tmp_path):
    _original()
    copy = tmp_path / "tt.json"

    _run(_workbook(tmp_path, [_row()]), to_json=copy)
    assert not Product.objects.filter(pk__startswith="tt-").exists()

    _run(copy)

    assert Product.objects.get(pk="tt-inj-f67-01").data["partNumber"] == "TT-INJ-F67-01"


@pytest.mark.django_db
def test_the_committed_json_matches_existing_seed_products():
    # La copia del repo tiene que poder cargarse sobre la semilla del catálogo.
    call_command("import_catalog", stdout=StringIO())

    output = _run(DATA_FILE, dry_run=True)

    assert "TorqueTrack products to create: 100" in output


@pytest.mark.parametrize(
    ("title", "base"),
    [
        ("6.6L Duramax L5P Turbo Actuator - GM OE", "6.6L Duramax L5P Turbo Actuator"),
        ("2019-2021 6.7L Cummins Injector - Bosch 0445124047", "2019-2021 6.7L Cummins Injector"),
        ("6.7L Cummins DOC / DPF Assembly", "6.7L Cummins DOC / DPF Assembly"),
    ],
)
def test_tt_title_swaps_the_original_brand_for_torquetrack(title, base):
    assert tt_title(title) == f"{base} - TorqueTrack"
