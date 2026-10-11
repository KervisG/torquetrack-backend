"""Cuentas: credenciales, alta de `User`, la forma del usuario de sesión y los
enlaces por correo (restablecer contraseña, verificar el email y activar la
invitación al portal). Un módulo por tema; este `__init__` reexporta la API
pública para que los imports `from apps.authentication.services import ...` no
dependan de la división. Los tests parchean el módulo donde se usa cada
función (`apps.authentication.services.tokens.run_in_background`), no este."""
from apps.authentication.services.credentials import (
    EMAIL_ALREADY_EXISTS,
    change_password,
    create_account,
    parse_email,
)
from apps.authentication.services.email_verification import (
    consume_email_verification,
    resend_verification_email,
    send_existing_account_email,
    send_verification_email,
)
from apps.authentication.services.login import (
    authenticate_user,
    csrf_token_payload,
    serialize_session_user,
)
from apps.authentication.services.password_reset import (
    confirm_password_reset,
    request_password_reset,
)
from apps.authentication.services.tokens import (
    invited_emails,
    issue_account_token,
    issue_activation_token,
    lock_activation_token,
)

__all__ = [
    "EMAIL_ALREADY_EXISTS",
    "authenticate_user",
    "change_password",
    "confirm_password_reset",
    "consume_email_verification",
    "create_account",
    "csrf_token_payload",
    "invited_emails",
    "issue_account_token",
    "issue_activation_token",
    "lock_activation_token",
    "parse_email",
    "request_password_reset",
    "resend_verification_email",
    "send_existing_account_email",
    "send_verification_email",
    "serialize_session_user",
]
