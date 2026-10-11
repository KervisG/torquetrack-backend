"""Reparto entre columnas tipadas y JSON, compartido por `Product` y
`Application`.

Cada modelo declara `COLUMN_FIELDS` (clave camelCase de la API -> columna y
tipo); lo que no está ahí queda en `attributes`. `data` arma la forma de la
API desde las dos partes y asignarla las reparte."""

from decimal import Decimal, InvalidOperation

from apps.common.numbers import money_decimal


class ColumnValueError(ValueError):
    """Un valor que no entra en su columna; `field` es la clave de la API."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def to_column(key: str, kind: str, value):
    """Vacío es "sin dato" (`None`), igual que una clave ausente del JSON."""
    if value is None or value == "":
        return None
    if kind == "text":
        return str(value)
    if kind == "bool":
        if not isinstance(value, bool):
            raise ColumnValueError(key, f"{key} must be true or false")
        return value
    if kind == "list":
        if not isinstance(value, list):
            raise ColumnValueError(key, f"{key} must be a list")
        return [str(entry) for entry in value]
    if isinstance(value, bool):
        raise ColumnValueError(key, f"{key} must be a number")
    if kind == "year":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ColumnValueError(key, f"{key} must be a year") from None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ColumnValueError(key, f"{key} must be a number") from None
    if not number.is_finite():
        raise ColumnValueError(key, f"{key} must be a number")
    return money_decimal(number)


def from_column(kind: str, value):
    # El JSON de la API lleva números, no el texto con que DRF serializa un `Decimal`.
    return float(value) if kind == "money" else value


class ColumnDataMixin:
    """Para un modelo con `COLUMN_FIELDS` y el JSON `attributes`."""

    COLUMN_FIELDS: dict[str, tuple[str, str]] = {}

    @property
    def data(self) -> dict:
        """La forma camelCase que consume la API: `attributes` más las
        columnas con valor."""
        merged = dict(self.attributes or {})
        for key, (column, kind) in self.COLUMN_FIELDS.items():
            value = getattr(self, column)
            if value is not None:
                merged[key] = from_column(kind, value)
        return merged

    @data.setter
    def data(self, value: dict) -> None:
        """Reemplaza todo: una clave de columna ausente la deja en `None`.
        `ColumnValueError` si un valor no entra en su columna."""
        remaining = dict(value or {})
        columns = {
            column: to_column(key, kind, remaining.pop(key, None))
            for key, (column, kind) in self.COLUMN_FIELDS.items()
        }
        for column, column_value in columns.items():
            setattr(self, column, column_value)
        self.attributes = remaining
