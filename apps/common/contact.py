"""Forma válida de un correo y de un teléfono de contacto. El SPA tiene su
espejo en `src/lib/validators/checkout-customer.ts`."""
from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

PHONE_MIN_DIGITS = 10
PHONE_MAX_DIGITS = 15
_NON_DIGIT = re.compile(r"\D")


def is_valid_email(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        validate_email(value.strip())
    except ValidationError:
        return False
    return True


def is_plausible_phone(value) -> bool:
    """10 a 15 dígitos (E.164) sin contar el formato: espacios, guiones,
    paréntesis, puntos y el `+`. Las letras no son formato."""
    if not isinstance(value, str) or re.search(r"[^\d\s()+.\-]", value):
        return False
    return PHONE_MIN_DIGITS <= len(_NON_DIGIT.sub("", value)) <= PHONE_MAX_DIGITS
