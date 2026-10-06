"""`error_payload` de `apps/common/errors.py`: el body de un error de servicio,
con `field` solo cuando el error es de un campo del input."""
from apps.common.errors import error_payload


def test_without_a_field_the_body_is_only_the_message():
    assert error_payload("Cart is empty") == {"error": "Cart is empty"}


def test_a_field_is_added_as_snake_case():
    assert error_payload("Invalid", "partNumber") == {"error": "Invalid", "field": "part_number"}
    assert error_payload("Invalid", "zip") == {"error": "Invalid", "field": "zip"}
    assert error_payload("Invalid", "address1") == {"error": "Invalid", "field": "address1"}


def test_a_status_is_kept_for_the_dict_contract():
    assert error_payload("Taken", "email", status=409) == {
        "error": "Taken",
        "field": "email",
        "status": 409,
    }
