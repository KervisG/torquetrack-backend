"""Ejemplos de request y response del esquema OpenAPI de `apps.cart`.

Los mensajes de `{"error": ...}` son los literales de `services/storefront.py`
y de `apps.catalog.services.pricing`. Si un mensaje cambia en el código, hay
que cambiarlo aquí.
"""
from drf_spectacular.utils import OpenApiExample

from apps.authorization.docs.examples import error_example

CART_REQUEST = OpenApiExample(
    "One line",
    value={"items": [{"id": "gm-65-injection-pump-dorman-502550", "qty": 2}]},
    request_only=True,
)
ACKNOWLEDGE_REQUEST = OpenApiExample(
    "Accept the price notices",
    value={
        "items": [{"id": "gm-65-injection-pump-dorman-502550", "qty": 1}],
        "acknowledgePrices": True,
    },
    request_only=True,
)
CART = OpenApiExample(
    "Repriced cart",
    value={
        "items": [
            {
                "id": "gm-65-injection-pump-dorman-502550",
                "qty": 2,
                "title": "6.5L Turbo Diesel Fuel Injection Pump",
                "partNumber": "502-550",
                "price": 189.99,
                "coreCharge": 50.0,
                "lineTotal": 379.98,
                "priceChanged": False,
            }
        ],
        "subtotal": 379.98,
        "core": 100.0,
        "notices": [],
    },
    response_only=True,
)
PRICE_CHANGED_CART = OpenApiExample(
    "Price changed since it was added",
    value={
        "items": [
            {
                "id": "gm-65-injection-pump-dorman-502550",
                "qty": 1,
                "title": "6.5L Turbo Diesel Fuel Injection Pump",
                "partNumber": "502-550",
                "price": 199.99,
                "coreCharge": 50.0,
                "lineTotal": 199.99,
                "priceChanged": True,
                "previousPrice": 189.99,
            }
        ],
        "subtotal": 199.99,
        "core": 50.0,
        "notices": [
            "The price of 6.5L Turbo Diesel Fuel Injection Pump has changed "
            "from $189.99 to $199.99."
        ],
    },
    response_only=True,
)
EMPTY_CART = OpenApiExample(
    "Empty cart",
    value={"items": [], "subtotal": 0.0, "core": 0.0, "notices": []},
    response_only=True,
)

MALFORMED_ITEMS = error_example(
    "Malformed items", "Items must be a list of objects with an id and qty"
)
INVALID_QUANTITY = error_example(
    "Quantity out of range", "Item quantity must be a whole number from 1 to 99"
)
DUPLICATE_ITEM = error_example("Repeated product", "Each product can appear only once in the cart")
TOO_MANY_LINES = error_example("Too many lines", "A cart can hold at most 100 different products")
UNAVAILABLE_PRODUCT = error_example(
    "Inactive or unknown product", "These products are not available: no-such-part"
)
