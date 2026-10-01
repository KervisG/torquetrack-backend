"""Reset de contraseña por correo: `/api/password-reset/` y
`/api/password-reset/confirm/`."""
from __future__ import annotations

from django.db import transaction
from django.utils.html import format_html

from apps.authentication.models import AccountToken, User
from apps.authentication.services.credentials import change_password, parse_email, password_error
from apps.authentication.services.tokens import (
    issue_account_token,
    lock_account_token,
    send_account_email,
)
from apps.common.links import app_url

PASSWORD_RESET_REQUESTED = {
    "ok": True,
    "message": "If an account exists for that email, we sent a link to reset the password.",
}
_INVALID_RESET = {"error": "Invalid or expired reset link", "status": 400}


def request_password_reset(payload: dict) -> dict:
    """Siempre devuelve el mismo body, exista o no la cuenta, para no permitir
    enumerar correos."""
    email = parse_email(payload.get("email"))
    user = User.objects.filter(email=email, active=True).first() if email else None
    if user is not None:
        token = issue_account_token(user, AccountToken.PASSWORD_RESET)
        send_account_email(
            user,
            "Reset your TorqueTrack password",
            format_html(
                "<p>We received a request to reset the password of your TorqueTrack "
                "account.</p>"
                '<p><a href="{}">Reset your password</a></p>'
                "<p>This link expires in 1 hour and can be used only once. If you did "
                "not ask for it, you can ignore this email.</p>",
                app_url(f"/reset-password?token={token}"),
            ),
        )
    return dict(PASSWORD_RESET_REQUESTED)


def confirm_password_reset(payload: dict) -> dict:
    password = payload.get("password")
    with transaction.atomic():
        record = lock_account_token(payload.get("token"), AccountToken.PASSWORD_RESET)
        if record is None:
            return dict(_INVALID_RESET)
        if not isinstance(password, str) or not password:
            return {"error": "Password required", "status": 400}
        user = record.user
        # Una contraseña rechazada no consume el enlace: la persona puede
        # reintentar con una más fuerte.
        error = password_error(password, user)
        if error is not None:
            return {"error": error, "status": 400}

        change_password(user, password)
    return {"ok": True}
