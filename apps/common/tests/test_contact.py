"""`apps/common/contact.py`: correo con `validate_email` de Django y teléfono
de 10 a 15 dígitos sin contar el formato (espacios, guiones, paréntesis,
puntos, `+`); las letras no son formato."""
import pytest

from apps.common.contact import is_plausible_phone, is_valid_email


@pytest.mark.parametrize("value", ["buyer@example.com", " Buyer@Example.co "])
def test_valid_emails(value):
    assert is_valid_email(value)


@pytest.mark.parametrize("value", [None, "", "  ", "buyer", "buyer@example", "@example.com", 42])
def test_invalid_emails(value):
    assert not is_valid_email(value)


@pytest.mark.parametrize(
    "value",
    ["9415550100", "(941) 555-0100", "+1 941.555.0100", "+44 20 7946 0958", "123456789012345"],
)
def test_plausible_phones(value):
    assert is_plausible_phone(value)


@pytest.mark.parametrize(
    "value", [None, "", "555-0100", "1234567890123456", "941-555-0100 ext 2", "call me", 9415550100]
)
def test_implausible_phones(value):
    assert not is_plausible_phone(value)
