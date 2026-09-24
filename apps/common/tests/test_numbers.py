"""`to_number` y `money` son la única coerción numérica y el único redondeo de
dinero del backend; sin I/O ni base de datos."""
from decimal import Decimal

import pytest

from apps.common.numbers import money, money_decimal, to_number


@pytest.mark.parametrize(
    "raw, expected",
    [(1.005, 1.01), (2.675, 2.68), ("10.125", 10.13), (0.004, 0.0), (None, 0.0), ("abc", 0.0)],
)
def test_money_rounds_half_up_to_cents(raw, expected):
    assert money(raw) == expected


def test_money_ignores_non_finite_values():
    assert money(float("inf")) == 0.0
    assert money("NaN") == 0.0


def test_money_decimal_keeps_two_decimal_places():
    assert money_decimal("19.999") == Decimal("20.00")


@pytest.mark.parametrize("raw", [None, False, "", 0, 0.0, "abc", [1], {}])
def test_to_number_uses_the_default_for_empty_zero_and_non_numeric_values(raw):
    assert to_number(raw, 7.0) == 7.0


@pytest.mark.parametrize("raw, expected", [("2", 2.0), (3, 3.0), ("1.5", 1.5), (True, 1.0)])
def test_to_number_parses_numbers_and_numeric_text(raw, expected):
    assert to_number(raw, 7.0) == expected


def test_to_number_keeps_a_zero_written_as_text():
    # Un "0" tipeado es un número, no un campo vacío: lo decide quien llama.
    assert to_number("0", 7.0) == 0.0
