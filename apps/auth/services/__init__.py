"""Cuentas: credenciales, alta de `User`, la forma del usuario de sesión y los
enlaces por correo (restablecer contraseña, verificar el email y activar la
invitación al portal). Este `__init__` reexporta la API pública; dentro del
paquete cada módulo importa del módulo concreto. Los tests parchean el módulo
donde se usa cada función (`apps.auth.services.tokens.run_in_background`)."""
from apps.auth.services.credentials import (
    change_password,
    create_account,
    parse_email,
)
from apps.auth.services.email_verification import (
    consume_email_verification,
    resend_verification_email,
    send_existing_account_email,
    send_verification_email,
)
from apps.auth.services.login import (
    authenticate_user,
    csrf_token_payload,
    serialize_session_user,
)
from apps.auth.services.password_reset import (
    confirm_password_reset,
    request_password_reset,
)
from apps.auth.services.tokens import (
    invited_emails,
    issue_account_token,
    issue_activation_token,
    lock_activation_token,
)

__all__ = [
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
