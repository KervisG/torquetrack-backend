"""Ejemplos de request y response del esquema OpenAPI de `apps.authentication`.

Los mensajes de `{"error": ...}` son los literales de `views.py` y
`services/`; los de `{"detail": ...}` son los que arma DRF. Si un mensaje
cambia en el código, hay que cambiarlo aquí. Los helpers, los errores de
DRF que comparte con el panel (JSON mal formado, CSRF) y `OK` son los de
`apps.authorization.docs.examples`, que está debajo de esta app.
"""
from drf_spectacular.utils import OpenApiExample

from apps.authorization.docs.examples import detail_example, error_example

# --- errores de DRF ---------------------------------------------------------------

THROTTLED = detail_example(
    "Throttled", "Request was throttled. Expected available in 3540 seconds."
)

# --- errores de la aplicación -----------------------------------------------------

WEAK_PASSWORD = error_example(
    "Weak password", "This password is too common. This password is entirely numeric."
)

# --- cuerpos de éxito --------------------------------------------------------------

CUSTOMER_SESSION = OpenApiExample(
    "Customer session",
    value={
        "authenticated": True,
        "user": {
            "id": "U_CUSTOMER",
            "email": "pat@example.com",
            "firstName": "Pat",
            "lastName": "Fleet",
            "isStaff": False,
            "role": None,
            "permissions": [],
            "emailVerified": False,
        },
        "csrfToken": "<token>",
    },
)
STAFF_SESSION = OpenApiExample(
    "Staff session",
    value={
        "authenticated": True,
        "user": {
            "id": "U_8F3K2",
            "email": "ana.torres@example.com",
            "firstName": "Ana",
            "lastName": "Torres",
            "isStaff": True,
            "role": {"slug": "employee", "name": "Employee", "fullAccess": False},
            "permissions": ["dashboard.view", "products.view"],
            "emailVerified": True,
        },
        "csrfToken": "<token>",
    },
)

# --- requests ---------------------------------------------------------------------

LOGIN_REQUEST = OpenApiExample(
    "Credentials",
    value={"email": "pat@example.com", "password": "Diesel-Torque-2026!"},
    request_only=True,
)
PASSWORD_RESET_REQUEST = OpenApiExample(
    "Email", value={"email": "pat@example.com"}, request_only=True
)
PASSWORD_RESET_CONFIRM_REQUEST = OpenApiExample(
    "New password",
    value={"token": "<token from the email link>", "password": "Diesel-Torque-2026!"},
    request_only=True,
)
