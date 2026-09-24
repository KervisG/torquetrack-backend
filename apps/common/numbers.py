import math
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_number(value, default: float = 0.0) -> float:
    """`float(value)`, o `default` para `None`, `False`, `""`, `0` y todo lo
    que no es número: un cero en el catálogo o en el body significa "sin dato",
    no un valor, así `to_number(qty, 1)` nunca cobra cero unidades.
    """
    if value in (None, False, "", 0):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def money_decimal(value) -> Decimal:
    """Única regla de redondeo de dinero: centavos con `ROUND_HALF_UP`.

    Se parte de `repr(float)` para redondear el número tal como se escribió
    (1.005 -> 1.01) y no su representación binaria (1.00499...)."""
    number = to_number(value, 0.0)
    if not math.isfinite(number):
        return Decimal("0.00")
    return Decimal(repr(float(number))).quantize(CENT, rounding=ROUND_HALF_UP)


def money(value) -> float:
    """Monto en dólares redondeado a centavos, como `float` para el JSON."""
    return float(money_decimal(value))
