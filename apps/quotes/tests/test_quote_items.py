"""Líneas de la cotización en `quote_items`, con la misma forma que las del
pedido: convertir una cotización es copiar filas."""
import pytest

from apps.quotes.models import Quote, QuoteItem

LINE = {
    "title": "Custom labor",
    "partNumber": "",
    "quantity": 1,
    "unitPrice": 95.0,
    "coreCharge": 0.0,
}


@pytest.mark.django_db
def test_quote_lines_are_rows_and_data_returns_them():
    Quote.objects.create(id="QID1", number="Q1", data={"items": [LINE], "memo": "rush"})

    quote = Quote.objects.get(pk="QID1")
    assert QuoteItem.objects.filter(quote=quote).count() == 1
    assert quote.details == {"memo": "rush"}
    assert quote.data == {"memo": "rush", "items": [LINE]}


@pytest.mark.django_db
def test_a_quote_without_lines_has_no_items_key():
    Quote.objects.create(id="QID1", number="Q1", data={"memo": "rush"})

    assert Quote.objects.get(pk="QID1").data == {"memo": "rush"}
