"""Serializers que solo describen los bodies en el esquema OpenAPI.

Sin docstrings en las clases: drf-spectacular los publica como descripción
del componente, y lo que ve quien consume la API va en inglés.

Ninguna view los usa en runtime: las views de `apps.authorization` leen
`request.data` a mano y `services/` arma los dicts. Si cambia la forma
de un dict en `services/`, hay que cambiarla aquí también. Los errores,
`OkResponseSerializer` y `RoleSummarySerializer` los reutiliza
`apps.authentication.docs.schemas` para la sesión y el login.
"""
from rest_framework import serializers

# --- errores -------------------------------------------------------------------


# Único formato de error de la API: lo arman las views y también
# `config.exceptions.api_exception_handler` para los errores de DRF (CSRF,
# throttle, JSON mal formado, 405, 415). Un error de validación por campo de un
# serializer de DRF agregaría `fields`; hoy ninguna view pública lo produce.
# `field` lo agrega `apps.common.errors.error_payload` cuando el error es de un
# campo del body; sin campo, la clave no aparece.
class ErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Literal English error message.")
    field = serializers.CharField(
        required=False,
        help_text=(
            "snake_case name of the input field the error is about (for example `zip`, "
            "`state`, `price`, `shipping_zip`). Omitted when the error is not about a "
            "single field."
        ),
    )


class OkResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()


# --- roles y usuarios del panel --------------------------------------------------


class RoleSummarySerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    fullAccess = serializers.BooleanField()


class AdminRoleSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()
    fullAccess = serializers.BooleanField()
    permissions = serializers.ListField(
        child=serializers.CharField(),
        help_text="Catalog codes. A full access role lists every code.",
    )


class RoleWriteRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    fullAccess = serializers.BooleanField(required=False, default=False)
    permissions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Ignored when `fullAccess` is true.",
    )


class AdminUserSerializer(serializers.Serializer):
    id = serializers.CharField()
    email = serializers.CharField()
    firstName = serializers.CharField()
    lastName = serializers.CharField()
    name = serializers.CharField(help_text="First and last name; the email when both are empty.")
    active = serializers.BooleanField()
    isStaff = serializers.BooleanField(help_text="`true` when the user is active and has a role.")
    role = RoleSummarySerializer(allow_null=True)
    permissions = serializers.ListField(child=serializers.CharField())
    createdAt = serializers.DateTimeField()


class AdminUserResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    user = AdminUserSerializer()


# Pese al `PUT`, los dos campos son opcionales: el service solo toca los que
# llegan. Cualquier otro campo (email, contraseña, nombres) es un 400: la
# cuenta es de su dueño y el panel solo decide su acceso.
class AdminUserUpdateRequestSerializer(serializers.Serializer):
    role = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Slug of an existing role; `null` removes the role and panel access.",
    )
    active = serializers.BooleanField(required=False, help_text="Must be a JSON boolean.")
