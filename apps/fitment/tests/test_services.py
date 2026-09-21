"""Near-verbatim port of `lib/fitment.ts`'s `checkProductFitment` (task 4.2).

Every case here is pinned to the actual TypeScript source read this run,
not a paraphrase:
- `makeMatches`: `"chevrolet / gmc"`/`"chevrolet/gmc"` alias, exact `"ram"`
  aliasing to `dodge`, otherwise substring match either direction.
- Year range: only checked when vehicle year AND product yearFrom AND
  product yearTo are all truthy (falsy year/range silently skips the
  check, matching JS's `year && from && to` guard).
- Engine: `Math.abs(pe-ve) > .15` on the FIRST number found by regex in
  each raw string (`engineFamily` falls back to `engine`); the warning and
  reason messages both use the RAW field values, not the parsed numbers.
"""
from apps.fitment.services import check_product_fitment


def test_compatible_when_everything_matches():
    product = {"make": "Ford", "yearFrom": 1994, "yearTo": 1997, "engineFamily": "7.3"}
    vehicle = {"make": "Ford", "year": 1996, "engine": "7.3"}

    result = check_product_fitment(product, vehicle)

    assert result == {"compatible": True, "reasons": [], "warnings": []}


def test_year_outside_range_is_a_reason():
    product = {"make": "Ford", "yearFrom": 1994, "yearTo": 1997}
    vehicle = {"make": "Ford", "year": 2005}

    result = check_product_fitment(product, vehicle)

    assert result["compatible"] is False
    assert result["reasons"] == ["year 2005 is outside 1994-1997"]


def test_missing_year_range_skips_year_check():
    product = {"make": "Ford"}
    vehicle = {"make": "Ford", "year": 2005}

    result = check_product_fitment(product, vehicle)

    assert result["reasons"] == []


def test_chevrolet_gmc_alias_matches_either_make():
    product = {"make": "Chevrolet / GMC"}

    assert check_product_fitment(product, {"make": "GMC"})["compatible"] is True
    assert check_product_fitment(product, {"make": "Chevrolet"})["compatible"] is True
    assert check_product_fitment(product, {"make": "Ford"})["compatible"] is False


def test_ram_alias_matches_dodge():
    product = {"make": "Ram"}

    assert check_product_fitment(product, {"make": "Dodge Ram 2500"})["compatible"] is True
    assert check_product_fitment(product, {"make": "Ford"})["compatible"] is False


def test_engine_mismatch_beyond_tolerance_is_a_reason():
    product = {"engineFamily": "6.5"}
    vehicle = {"engine": "6.9"}

    result = check_product_fitment(product, vehicle)

    assert result["compatible"] is False
    assert result["reasons"] == ["engine 6.9 does not match required 6.5"]


def test_engine_mismatch_within_tolerance_is_compatible():
    product = {"engineFamily": "6.5"}
    vehicle = {"engine": "6.6499"}

    result = check_product_fitment(product, vehicle)

    assert result["compatible"] is True
    assert result["reasons"] == []


def test_missing_vehicle_engine_produces_a_warning_not_a_reason():
    product = {"engineFamily": "6.5"}
    vehicle = {}

    result = check_product_fitment(product, vehicle)

    assert result["compatible"] is True
    assert result["reasons"] == []
    assert result["warnings"] == [
        "VIN decoder did not return engine displacement; verify 6.5 manually before ordering"
    ]


def test_no_make_on_either_side_defaults_to_compatible():
    result = check_product_fitment({}, {})

    assert result["compatible"] is True
