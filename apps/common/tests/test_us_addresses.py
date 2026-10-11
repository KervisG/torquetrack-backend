"""Lista canónica de estados de EE. UU. a los que envía la tienda y la forma
válida del ZIP. Sin base de datos: son constantes y funciones puras."""
import pytest

from apps.common.us_addresses import (
    INVALID_SHIPPING_ZIP,
    UNKNOWN_SHIPPING_ZIP,
    US_STATE_CODES,
    ZIP_STATE_EXCEPTIONS,
    ZIP_STATE_MISMATCH,
    is_valid_zip,
    normalize_state_code,
    shipping_zip_error,
    states_for_zip,
    zip_states_by_prefix,
)


def test_the_list_has_the_50_states_dc_and_the_five_inhabited_territories():
    assert len(US_STATE_CODES) == 56
    assert {"FL", "CA", "NY", "TX", "AK", "HI", "DC"} <= US_STATE_CODES
    assert {"PR", "VI", "GU", "AS", "MP"} <= US_STATE_CODES


@pytest.mark.parametrize("code", ["AA", "AE", "AP", "FM", "MH", "PW"])
def test_military_and_freely_associated_codes_are_not_shipped_to(code):
    # UPS y FedEx no entregan en APO/FPO ni en los estados libremente asociados.
    assert code not in US_STATE_CODES
    assert normalize_state_code(code) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("FL", "FL"), (" fl ", "FL"), ("dc", "DC"), ("Pr", "PR")],
)
def test_a_valid_code_is_trimmed_and_uppercased(raw, expected):
    assert normalize_state_code(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "ZZ", "XX", "Florida", "F L", "FLA", 12, ["FL"]])
def test_anything_else_is_not_a_state_code(raw):
    assert normalize_state_code(raw) is None


@pytest.mark.parametrize("raw", ["33701", "33701-1234"])
def test_five_digit_and_zip_plus_four_are_valid(raw):
    assert is_valid_zip(raw)


@pytest.mark.parametrize("raw", ["", "3370", "337011", "33701-12", "ABCDE", None, 33701])
def test_other_zip_shapes_are_invalid(raw):
    assert not is_valid_zip(raw)


# --- ZIP contra estado (prefijos de 3 dígitos de USPS) -----------------------


@pytest.mark.parametrize(
    ("zip_code", "state"),
    [
        ("33701", "FL"),
        ("33701-1234", "FL"),
        ("32004", "FL"),
        ("34997", "FL"),
        ("30301", "GA"),
        ("90210", "CA"),
        ("00501", "NY"),
        ("00601", "PR"),
        ("00725", "PR"),
        ("00901", "PR"),
        ("00802", "VI"),
        ("20001", "DC"),
        ("20201", "DC"),
        ("20590", "DC"),
        ("20101", "VA"),
        ("96813", "HI"),
        ("96799", "AS"),
        ("96910", "GU"),
        ("96950", "MP"),
        ("99950", "AK"),
        ("06390", "NY"),
        ("88901", "NV"),
    ],
)
def test_a_zip_matches_the_state_of_its_usps_prefix(zip_code, state):
    assert states_for_zip(zip_code) == {state}
    assert shipping_zip_error(zip_code, state) is None


@pytest.mark.parametrize(
    ("zip_code", "state"),
    [
        ("33701", "GA"),
        ("30301", "FL"),
        ("33701-1234", "GA"),
        ("00601", "VI"),
        ("00802", "PR"),
        ("20001", "MD"),
        ("96799", "HI"),
        ("96950", "GU"),
        ("06390", "CT"),
    ],
)
def test_a_zip_from_another_state_does_not_match(zip_code, state):
    assert shipping_zip_error(zip_code, state) == ZIP_STATE_MISMATCH


@pytest.mark.parametrize(
    "zip_code",
    [
        "00001",  # 000-004 sin asignar
        "00401",
        "21301",  # 213 sin asignar
        "56901",  # 569 ya no figura en L002
        "98701",  # 987 sin asignar
        "09001",  # APO/FPO AE
        "34001",  # APO/FPO AA, aunque la lista de USPS lo etiquete por Miami
        "96201",  # APO/FPO AP
        "96940",  # Palau
        "96960",  # Islas Marshall
    ],
)
def test_unassigned_military_and_freely_associated_zips_are_not_valid(zip_code):
    assert states_for_zip(zip_code) == frozenset()
    for state in ("FL", "NY", "CA", "GU", "DC"):
        assert shipping_zip_error(zip_code, state) == UNKNOWN_SHIPPING_ZIP


@pytest.mark.parametrize(
    ("zip_code", "states"),
    [("73960", {"OK", "TX"}), ("03902", {"ME", "NH"}), ("56520", {"MN", "ND"})],
)
def test_a_zip_that_crosses_a_state_line_matches_every_state_it_serves(zip_code, states):
    for state in states:
        assert shipping_zip_error(zip_code, state) is None
    assert states_for_zip(zip_code) == states
    assert shipping_zip_error(zip_code, "FL") == ZIP_STATE_MISMATCH


def test_a_malformed_zip_reports_the_shape_error_first():
    assert shipping_zip_error("3370", "FL") == INVALID_SHIPPING_ZIP
    assert states_for_zip(None) == frozenset()


def test_the_table_covers_all_56_codes_and_florida_never_shares_a_zip():
    # El nexo fiscal es solo FL: ningún ZIP puede valer para FL y otro estado.
    # AS (96799) y MP (96950-96952) comparten prefijo con HI y GU.
    covered = set(zip_states_by_prefix().values()).union(*ZIP_STATE_EXCEPTIONS.values())
    assert covered == US_STATE_CODES
    florida = {prefix for prefix, state in zip_states_by_prefix().items() if state == "FL"}
    # 340 es APO/FPO AA; 343, 345 y 348 no están asignados en L002.
    assert florida == {f"{n:03d}" for n in range(320, 350)} - {"340", "343", "345", "348"}
    assert all("FL" not in states for states in ZIP_STATE_EXCEPTIONS.values())
