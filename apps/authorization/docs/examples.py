"""Ejemplos de request y response del esquema OpenAPI de `apps.authorization`.

Los mensajes de `{"error": ...}` son los literales de `views.py` y
`services/`; los de `{"detail": ...}` son los que arma DRF. Si un
mensaje cambia en el código, hay que cambiarlo aquí. `apps.authentication.docs`
reutiliza `error_example`, `detail_example`, los errores de DRF y `OK`.
"""
from drf_spectacular.utils import OpenApiExample


def error_example(name: str, message: str) -> OpenApiExample:
    return OpenApiExample(name, value={"error": message})


def detail_example(name: str, message: str) -> OpenApiExample:
    return OpenApiExample(name, value={"detail": message})


# --- errores de DRF ---------------------------------------------------------------

MALFORMED_JSON = detail_example(
    "Malformed JSON", "JSON parse error - Expecting value: line 1 column 1 (char 0)"
)
CSRF_FAILED = detail_example("CSRF token missing", "CSRF Failed: CSRF token missing.")
UNSUPPORTED_MEDIA_TYPE = detail_example(
    "Form body",
    'Unsupported media type "application/x-www-form-urlencoded" in request.',
)

# --- errores de la aplicación -----------------------------------------------------

UNAUTHORIZED = error_example("No staff session", "Unauthorized")
FORBIDDEN = error_example("Missing users.manage", "Forbidden")
USER_NOT_FOUND = error_example("User not found", "User not found")
INVALID_ROLE = error_example("Invalid role", "Valid role required")
ACTIVE_NOT_BOOLEAN = error_example("active is not a boolean", "active must be a boolean")
ONLY_ROLE_AND_ACTIVE = error_example(
    "Field other than role or active", "Only role and active can be changed"
)
GRANT_FULL_ACCESS = error_example(
    "Granting full access", "Only a full access user can grant full access"
)
MODIFY_FULL_ACCESS = error_example(
    "Modifying a full access user", "Only a full access user can modify a full access user"
)
GRANT_MISSING_PERMISSIONS = error_example(
    "Granting permissions the actor lacks", "You cannot grant permissions you do not have"
)
MODIFY_MORE_PRIVILEGED = error_example(
    "Target has permissions the actor lacks",
    "You cannot modify a user with permissions you do not have",
)
OWN_ROLE_OR_ACTIVE = error_example(
    "Own role or status", "You cannot change your own role or active status"
)
DEACTIVATE_FULL_ACCESS = error_example(
    "Deactivating a full access user", "A full access user must remain active"
)
LAST_FULL_ACCESS = error_example(
    "Last full access user", "At least one active full access user is required"
)
DELETE_OWN_ACCOUNT = error_example("Own account", "You cannot delete your own account")
DELETE_FULL_ACCESS = error_example(
    "Full access target", "A full access account cannot be deleted"
)
DELETE_MORE_PRIVILEGED = error_example(
    "Target has permissions the actor lacks",
    "You cannot delete a user with permissions you do not have",
)

# --- cuerpos de éxito --------------------------------------------------------------

OK = OpenApiExample("Ok", value={"ok": True})
ADMIN_USER = {
    "id": "U_8F3K2",
    "email": "ana.torres@example.com",
    "firstName": "Ana",
    "lastName": "Torres",
    "name": "Ana Torres",
    "active": True,
    "isStaff": True,
    "role": {"slug": "employee", "name": "Employee", "fullAccess": False},
    "permissions": ["dashboard.view", "products.view"],
    "createdAt": "2026-09-23T18:54:00.123456Z",
}
ADMIN_USER_RESULT = OpenApiExample("User saved", value={"ok": True, "user": ADMIN_USER})
# drf-spectacular envuelve en una lista los ejemplos de respuestas `many=True`.
ADMIN_USER_LIST = OpenApiExample("Users", value=ADMIN_USER)
ADMIN_ROLE_LIST = OpenApiExample(
    "Roles", value={"id": 1, "slug": "admin", "name": "Admin", "fullAccess": True}
)

# --- requests ---------------------------------------------------------------------

ADMIN_USER_UPDATE_REQUEST = OpenApiExample(
    "Change role", value={"role": "employee"}, request_only=True
)
ADMIN_USER_REVOKE_REQUEST = OpenApiExample(
    "Remove panel access", value={"role": None}, request_only=True
)
ADMIN_USER_DEACTIVATE_REQUEST = OpenApiExample(
    "Deactivate", value={"active": False}, request_only=True
)
