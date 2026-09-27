"""Extensiones de drf-spectacular que documentan las views de `apps.authorization`.

Cada `OpenApiViewExtension` apunta a una view por su ruta de import y, solo al
generar el esquema, la reemplaza por una subclase decorada con
`@extend_schema`. Así las views de runtime no cargan documentación y un
cambio aquí nunca altera cómo responden.

`/api/admin/users/` no documenta `POST` porque no existe: nadie crea cuentas
desde el panel. Toda persona se registra como cliente y aquí solo se le
asigna un Role.
"""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

from apps.authorization.docs import examples as ex
from apps.authorization.docs.schemas import (
    AdminRoleSerializer,
    AdminUserResultSerializer,
    AdminUserSerializer,
    AdminUserUpdateRequestSerializer,
    ErrorResponseSerializer,
    OkResponseSerializer,
    RoleWriteRequestSerializer,
)

ADMIN_USERS_TAG = "admin: users"

USER_ID_PARAMETER = OpenApiParameter(
    "user_id",
    str,
    OpenApiParameter.PATH,
    description="User id (prefix `U`).",
)


# --- respuestas compartidas ------------------------------------------------------


ADMIN_UNAUTHORIZED = OpenApiResponse(
    ErrorResponseSerializer,
    description="No session, an inactive user, or a customer without a role.",
    examples=[ex.UNAUTHORIZED],
)
ADMIN_FORBIDDEN_READ = OpenApiResponse(
    ErrorResponseSerializer,
    description="Staff member without the `users.manage` permission.",
    examples=[ex.FORBIDDEN],
)
USER_NOT_FOUND = OpenApiResponse(ErrorResponseSerializer, examples=[ex.USER_NOT_FOUND])


def _admin_forbidden(description: str, *business_examples) -> OpenApiResponse:
    """403 de una ruta del panel que muta: el propio de la view, el de CSRF de
    DRF y los de las reglas de privilegio del service."""
    return OpenApiResponse(
        ErrorResponseSerializer,
        description=description,
        examples=[ex.FORBIDDEN, *business_examples, ex.CSRF_FAILED],
    )


ADMIN_ACCESS_RULES = (
    "Requires a staff session with the `users.manage` permission: without a staff "
    "session the response is `401`, and staff without the permission get `403`. "
    "Mutating requests also require the `X-CSRFToken` header. Not throttled."
)

PRIVILEGE_RULES = (
    "- Nobody can change their own role or active status.\n"
    "- A user without full access cannot modify or delete a user whose role grants "
    "permissions the actor lacks (full access included), nor assign a role that "
    "grants permissions the actor lacks (full access included).\n"
    "- The rules are evaluated with the affected accounts locked, so two concurrent "
    "requests cannot leave the store without an active full access user."
)


# --- panel: usuarios y roles ------------------------------------------------------


class AdminRolesViewExtension(OpenApiViewExtension):
    target_class = "apps.authorization.views.AdminRolesView"

    def view_replacement(self):
        class AdminRolesView(self.target_class):
            @extend_schema(
                operation_id="admin_roles_list",
                tags=[ADMIN_USERS_TAG],
                summary="List roles",
                description=(
                    f"{ADMIN_ACCESS_RULES}\n\n"
                    "Roles for the admin selectors: full access roles first, then by "
                    "`name`. Each row includes the catalog codes it grants."
                ),
                responses={
                    200: OpenApiResponse(
                        AdminRoleSerializer(many=True), examples=[ex.ADMIN_ROLE_LIST]
                    ),
                    401: ADMIN_UNAUTHORIZED,
                    403: ADMIN_FORBIDDEN_READ,
                },
            )
            def get(self, request):
                return super().get(request)

            @extend_schema(
                operation_id="admin_roles_create",
                tags=[ADMIN_USERS_TAG],
                summary="Create a role",
                description=(
                    f"{ADMIN_ACCESS_RULES}\n\n"
                    "The slug is derived from `name` and cannot be changed later. "
                    "A user without full access cannot create a full access role or "
                    "grant a permission they do not have."
                ),
                request=RoleWriteRequestSerializer,
                responses={
                    201: OpenApiResponse(AdminRoleSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    401: ADMIN_UNAUTHORIZED,
                    403: _admin_forbidden("Staff without `users.manage`, or a privilege rule."),
                },
            )
            def post(self, request):
                return super().post(request)

        return AdminRolesView


class AdminRoleDetailViewExtension(OpenApiViewExtension):
    target_class = "apps.authorization.views.AdminRoleDetailView"

    def view_replacement(self):
        class AdminRoleDetailView(self.target_class):
            @extend_schema(
                operation_id="admin_role_update",
                tags=[ADMIN_USERS_TAG],
                summary="Update a role",
                description=(
                    f"{ADMIN_ACCESS_RULES}\n\n"
                    "Replaces `name`, `fullAccess` and `permissions`. The slug in the "
                    "path does not change. The only full access role cannot lose full access."
                ),
                parameters=[
                    OpenApiParameter("slug", str, OpenApiParameter.PATH, description="Role slug.")
                ],
                request=RoleWriteRequestSerializer,
                responses={
                    200: OpenApiResponse(AdminRoleSerializer),
                    400: OpenApiResponse(ErrorResponseSerializer),
                    401: ADMIN_UNAUTHORIZED,
                    403: _admin_forbidden("Staff without `users.manage`, or a privilege rule."),
                    404: OpenApiResponse(ErrorResponseSerializer),
                },
            )
            def put(self, request, slug):
                return super().put(request, slug)

        return AdminRoleDetailView


class AdminUsersViewExtension(OpenApiViewExtension):
    target_class = "apps.authorization.views.AdminUsersView"

    def view_replacement(self):
        class AdminUsersView(self.target_class):
            @extend_schema(
                operation_id="admin_users_list",
                tags=[ADMIN_USERS_TAG],
                summary="List users",
                description=(
                    f"{ADMIN_ACCESS_RULES}\n\n"
                    "Lists every account, customers without a role included: full "
                    "access users first, then users with a role, then the rest; each "
                    "group by `createdAt` ascending. No pagination or filters.\n\n"
                    "Accounts are never created here: every person signs up as a "
                    "customer (`POST /api/register/`) and an admin then assigns a "
                    "role with `PUT /api/admin/users/{user_id}/`."
                ),
                responses={
                    200: OpenApiResponse(
                        AdminUserSerializer(many=True), examples=[ex.ADMIN_USER_LIST]
                    ),
                    401: ADMIN_UNAUTHORIZED,
                    403: ADMIN_FORBIDDEN_READ,
                },
            )
            def get(self, request):
                return super().get(request)

        return AdminUsersView


class AdminUserDetailViewExtension(OpenApiViewExtension):
    target_class = "apps.authorization.views.AdminUserDetailView"

    def view_replacement(self):
        @extend_schema_view(
            put=extend_schema(
                operation_id="admin_users_update",
                tags=[ADMIN_USERS_TAG],
                summary="Assign a role or change the active status",
                description=(
                    f"{ADMIN_ACCESS_RULES}\n\n"
                    "Only `role` and `active` are accepted; both are optional and only "
                    "the fields sent change. Any other field (`email`, `password`, "
                    "`firstName`, `lastName`, ...) is rejected with `400`: the account "
                    "belongs to its owner and the panel only decides its access.\n\n"
                    f"{PRIVILEGE_RULES}\n"
                    "- A full access user cannot be deactivated, and at least one "
                    "active full access user must remain.\n"
                    "- Deactivating ends all the user's sessions from their next "
                    "request; a role change applies from their next request.\n"
                    "- Records the `USER_UPDATED` activity with the email, role slug "
                    "and `active`."
                ),
                parameters=[USER_ID_PARAMETER],
                request=AdminUserUpdateRequestSerializer,
                examples=[
                    ex.ADMIN_USER_UPDATE_REQUEST,
                    ex.ADMIN_USER_REVOKE_REQUEST,
                    ex.ADMIN_USER_DEACTIVATE_REQUEST,
                ],
                responses={
                    200: OpenApiResponse(
                        AdminUserResultSerializer, examples=[ex.ADMIN_USER_RESULT]
                    ),
                    400: OpenApiResponse(
                        ErrorResponseSerializer,
                        description="A field other than `role`/`active`, a validation "
                        "error or malformed JSON.",
                        examples=[
                            ex.ONLY_ROLE_AND_ACTIVE,
                            ex.ACTIVE_NOT_BOOLEAN,
                            ex.INVALID_ROLE,
                            ex.MALFORMED_JSON,
                        ],
                    ),
                    401: ADMIN_UNAUTHORIZED,
                    403: _admin_forbidden(
                        "Missing `users.manage`, a privilege rule, or missing CSRF token.",
                        ex.OWN_ROLE_OR_ACTIVE,
                        ex.MODIFY_FULL_ACCESS,
                        ex.MODIFY_MORE_PRIVILEGED,
                        ex.GRANT_FULL_ACCESS,
                        ex.GRANT_MISSING_PERMISSIONS,
                        ex.DEACTIVATE_FULL_ACCESS,
                        ex.LAST_FULL_ACCESS,
                    ),
                    404: USER_NOT_FOUND,
                },
            ),
            delete=extend_schema(
                operation_id="admin_users_destroy",
                tags=[ADMIN_USERS_TAG],
                summary="Delete a user",
                description=(
                    f"{ADMIN_ACCESS_RULES}\n\n"
                    "Revokes all the user's sessions and deletes the account with its "
                    "tokens. A linked customer profile is kept (without a user) so "
                    "order history survives. Nobody can delete their own account or "
                    "a full access account, and a user without full access cannot "
                    "delete a user whose role grants permissions the actor lacks. "
                    "The rules are evaluated with the affected accounts locked.\n\n"
                    "Records the `USER_DELETED` activity with the email."
                ),
                parameters=[USER_ID_PARAMETER],
                request=None,
                responses={
                    200: OpenApiResponse(OkResponseSerializer, examples=[ex.OK]),
                    400: OpenApiResponse(
                        ErrorResponseSerializer, examples=[ex.DELETE_OWN_ACCOUNT]
                    ),
                    401: ADMIN_UNAUTHORIZED,
                    403: _admin_forbidden(
                        "Missing `users.manage`, a privilege rule, or missing CSRF token.",
                        ex.DELETE_FULL_ACCESS,
                        ex.DELETE_MORE_PRIVILEGED,
                    ),
                    404: USER_NOT_FOUND,
                },
            ),
        )
        class AdminUserDetailView(self.target_class):
            pass

        return AdminUserDetailView
