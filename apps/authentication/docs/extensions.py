"""Extensiones de drf-spectacular que documentan las views de `apps.authentication`.

Cada `OpenApiViewExtension` apunta a una view por su ruta de import y, solo al
generar el esquema, la reemplaza por una subclase decorada con
`@extend_schema`. Así las views de runtime no cargan documentación y un
cambio aquí nunca altera cómo responden.

La autenticación es `SessionAuthentication` de DRF, que drf-spectacular ya
describe como `cookieAuth`: no hace falta una extensión de esquema propia.
"""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema

from apps.authentication.docs import examples as ex
from apps.authentication.docs.schemas import (
    LoginRequestSerializer,
    PasswordResetConfirmRequestSerializer,
    PasswordResetRequestedResponseSerializer,
    PasswordResetRequestSerializer,
    SessionPayloadSerializer,
    SessionUnauthorizedResponseSerializer,
    VerifyEmailResendResponseSerializer,
)
from apps.authorization.docs import examples as shared_ex
from apps.authorization.docs.schemas import (
    ErrorResponseSerializer,
    OkResponseSerializer,
)

AUTH_TAG = "auth"


# --- respuestas compartidas ------------------------------------------------------


def _throttled(scopes: str) -> OpenApiResponse:
    return OpenApiResponse(
        ErrorResponseSerializer,
        description=f"Rate limit exceeded ({scopes}). Includes a `Retry-After` header.",
        examples=[ex.THROTTLED],
    )


CSRF_FORBIDDEN = OpenApiResponse(
    ErrorResponseSerializer,
    description="A valid session was sent without a matching `X-CSRFToken` header.",
    examples=[shared_ex.CSRF_FAILED],
)
MALFORMED_JSON = OpenApiResponse(
    ErrorResponseSerializer,
    description="The body is not valid JSON.",
    examples=[shared_ex.MALFORMED_JSON],
)
UNSUPPORTED_MEDIA_TYPE = OpenApiResponse(
    ErrorResponseSerializer,
    description=(
        "The body is not `application/json` (form-encoded or multipart). Only JSON "
        "is accepted, so a cross-site HTML form cannot reach this public route."
    ),
    examples=[shared_ex.UNSUPPORTED_MEDIA_TYPE],
)


# --- storefront ------------------------------------------------------------------


class LoginViewExtension(OpenApiViewExtension):
    target_class = "apps.authentication.views.LoginView"

    def view_replacement(self):
        class LoginView(self.target_class):
            @extend_schema(
                operation_id="auth_login",
                tags=[AUTH_TAG],
                summary="Log in",
                description=(
                    "Starts a session for a customer or a staff member; both use the "
                    "same account. Public, no CSRF check. Does not require a verified "
                    "email.\n\n"
                    "- Throttles: `login` (10/min per IP, every attempt) and "
                    "`login_account` (20 failed attempts/hour per email in the body; "
                    "a successful login resets it).\n"
                    "- Discards the previous session key and rotates the CSRF token: "
                    "replace the stored `csrfToken` with the one in the response.\n"
                    "- Merges the guest cart of the session into the account cart "
                    "(quantities of the same product are added, capped at 99); read "
                    "it again with `GET /api/cart/`.\n"
                    "- Unknown email, wrong password, inactive account and empty body "
                    "all return the same `401`."
                ),
                request=LoginRequestSerializer,
                examples=[ex.LOGIN_REQUEST],
                responses={
                    200: OpenApiResponse(
                        SessionPayloadSerializer,
                        description="Session started; sets the session cookie.",
                        examples=[ex.CUSTOMER_SESSION, ex.STAFF_SESSION],
                    ),
                    400: MALFORMED_JSON,
                    401: OpenApiResponse(
                        ErrorResponseSerializer,
                        description="Invalid credentials.",
                        examples=[
                            shared_ex.error_example(
                                "Invalid credentials", "Incorrect email or password"
                            )
                        ],
                    ),
                    415: UNSUPPORTED_MEDIA_TYPE,
                    429: _throttled("`login` or `login_account`"),
                },
            )
            def post(self, request):
                return super().post(request)

        return LoginView


class LogoutViewExtension(OpenApiViewExtension):
    target_class = "apps.authentication.views.LogoutView"

    def view_replacement(self):
        class LogoutView(self.target_class):
            @extend_schema(
                operation_id="auth_logout",
                tags=[AUTH_TAG],
                summary="Log out",
                description=(
                    "Ends the current session: deletes the session row, clears the "
                    "cookie; the account cart stays with the account and the new "
                    "session starts with an empty cart. Returns `200` with or without "
                    "a session. When the request carries a valid session it must send "
                    "`X-CSRFToken`; otherwise the session is kept and the response is "
                    "`403`. No body. Not throttled."
                ),
                request=None,
                responses={
                    200: OpenApiResponse(OkResponseSerializer, examples=[shared_ex.OK]),
                    403: CSRF_FORBIDDEN,
                },
            )
            def post(self, request):
                return super().post(request)

        return LogoutView


class SessionViewExtension(OpenApiViewExtension):
    target_class = "apps.authentication.views.SessionView"

    def view_replacement(self):
        class SessionView(self.target_class):
            @extend_schema(
                operation_id="auth_session_retrieve",
                tags=[AUTH_TAG],
                summary="Get the current session",
                description=(
                    "Returns the session user and always hands out a CSRF token, in "
                    "the body (`csrfToken`) and in the `csrftoken` cookie, even "
                    "without a session. Public. Not throttled."
                ),
                responses={
                    200: OpenApiResponse(
                        SessionPayloadSerializer,
                        examples=[ex.CUSTOMER_SESSION, ex.STAFF_SESSION],
                    ),
                    401: OpenApiResponse(
                        SessionUnauthorizedResponseSerializer,
                        description=(
                            "No session, or the user was deactivated or deleted. Still "
                            "carries a CSRF token."
                        ),
                        examples=[
                            OpenApiExample(
                                "No session",
                                value={"error": "Unauthorized", "csrfToken": "<token>"},
                            )
                        ],
                    ),
                },
            )
            def get(self, request):
                return super().get(request)

        return SessionView


class PasswordResetViewExtension(OpenApiViewExtension):
    target_class = "apps.authentication.views.PasswordResetView"

    def view_replacement(self):
        class PasswordResetView(self.target_class):
            @extend_schema(
                operation_id="auth_password_reset",
                tags=[AUTH_TAG],
                summary="Request a password reset link",
                description=(
                    "Always returns the same `200` body, whether or not the email "
                    "belongs to an account, so emails cannot be enumerated. Public.\n\n"
                    "- Throttles: `password_reset` (10/hour per IP) and "
                    "`password_reset_account` (5/hour per email, counted even when "
                    "no account exists).\n"
                    "- Only for an active account: creates a single-use reset token "
                    "valid for 1 hour and sends the \"Reset your TorqueTrack "
                    "password\" email in the background. Invalidates the earlier "
                    "pending reset links of the account: only the newest one works."
                ),
                request=PasswordResetRequestSerializer,
                examples=[ex.PASSWORD_RESET_REQUEST],
                responses={
                    200: OpenApiResponse(
                        PasswordResetRequestedResponseSerializer,
                        examples=[
                            OpenApiExample(
                                "Requested",
                                value={
                                    "ok": True,
                                    "message": (
                                        "If an account exists for that email, we sent "
                                        "a link to reset the password."
                                    ),
                                },
                            )
                        ],
                    ),
                    400: MALFORMED_JSON,
                    415: UNSUPPORTED_MEDIA_TYPE,
                    429: _throttled("`password_reset` or `password_reset_account`"),
                },
            )
            def post(self, request):
                return super().post(request)

        return PasswordResetView


class PasswordResetConfirmViewExtension(OpenApiViewExtension):
    target_class = "apps.authentication.views.PasswordResetConfirmView"

    def view_replacement(self):
        class PasswordResetConfirmView(self.target_class):
            @extend_schema(
                operation_id="auth_password_reset_confirm",
                tags=[AUTH_TAG],
                summary="Set a new password with a reset token",
                description=(
                    "Public; the emailed token is the proof. Throttle: "
                    "`password_reset_confirm` (10/hour per IP).\n\n"
                    "- The token is checked first: with an invalid token the answer "
                    "is always the invalid link error.\n"
                    "- A password rejected by the validators does not consume the "
                    "token.\n"
                    "- On success: stores the new password, invalidates every pending "
                    "reset token of the account and revokes all its sessions. Does "
                    "not start a session."
                ),
                request=PasswordResetConfirmRequestSerializer,
                examples=[ex.PASSWORD_RESET_CONFIRM_REQUEST],
                responses={
                    200: OpenApiResponse(OkResponseSerializer, examples=[shared_ex.OK]),
                    400: OpenApiResponse(
                        ErrorResponseSerializer,
                        description=(
                            "Invalid, expired or used token; missing password; weak "
                            "password; or malformed JSON."
                        ),
                        examples=[
                            shared_ex.error_example(
                                "Invalid token", "Invalid or expired reset link"
                            ),
                            shared_ex.error_example("Missing password", "Password required"),
                            ex.WEAK_PASSWORD,
                            shared_ex.MALFORMED_JSON,
                        ],
                    ),
                    415: UNSUPPORTED_MEDIA_TYPE,
                    429: _throttled("`password_reset_confirm`"),
                },
            )
            def post(self, request):
                return super().post(request)

        return PasswordResetConfirmView


class VerifyEmailResendViewExtension(OpenApiViewExtension):
    target_class = "apps.authentication.views.VerifyEmailResendView"

    def view_replacement(self):
        class VerifyEmailResendView(self.target_class):
            @extend_schema(
                operation_id="auth_verify_email_resend",
                tags=[AUTH_TAG],
                summary="Resend the email verification link",
                description=(
                    "Requires the session of any active user and the `X-CSRFToken` "
                    "header. Throttle: `verify_email_resend` (5/hour per user, per IP "
                    "without a session), checked before the session. No body.\n\n"
                    "When the email is not verified yet, creates a new verification "
                    "token valid for 48 hours and sends the \"Verify your TorqueTrack "
                    "email\" email in the background; invalidates the earlier pending "
                    "verification links, so only the newest one works. When it is "
                    "already verified, nothing is sent."
                ),
                request=None,
                responses={
                    200: OpenApiResponse(
                        VerifyEmailResendResponseSerializer,
                        examples=[
                            OpenApiExample(
                                "Link sent", value={"ok": True, "emailVerified": False}
                            ),
                            OpenApiExample(
                                "Already verified", value={"ok": True, "emailVerified": True}
                            ),
                        ],
                    ),
                    401: OpenApiResponse(
                        ErrorResponseSerializer,
                        description="No valid session.",
                        examples=[shared_ex.error_example("No session", "Unauthorized")],
                    ),
                    403: CSRF_FORBIDDEN,
                    429: _throttled("`verify_email_resend`"),
                },
            )
            def post(self, request):
                return super().post(request)

        return VerifyEmailResendView
