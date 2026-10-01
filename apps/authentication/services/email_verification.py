"""Verificación del email: el correo con el enlace, su reenvío
(`/api/verify-email/resend/`) y el consumo del token que usa
`POST /api/verify-email/` de `apps.customers`."""
from __future__ import annotations

from django.utils import timezone
from django.utils.html import format_html

from apps.authentication.models import AccountToken, User
from apps.authentication.services.tokens import (
    issue_account_token,
    lock_account_token,
    send_account_email,
)
from apps.common.links import app_url


def send_verification_email(user: User) -> None:
    token = issue_account_token(user, AccountToken.EMAIL_VERIFICATION)
    send_account_email(
        user,
        "Verify your TorqueTrack email",
        format_html(
            "<p>Confirm that this is your email to finish setting up your TorqueTrack "
            "account.</p>"
            '<p><a href="{}">Verify your email</a></p>'
            "<p>Once verified, past orders and quotes placed with this email are "
            "added to your account. This link expires in 48 hours.</p>",
            app_url(f"/verify-email?token={token}"),
        ),
    )


def send_existing_account_email(user: User) -> None:
    """Aviso al dueño cuando alguien intenta registrar su email: el registro
    responde igual que uno nuevo (para no enumerar cuentas) y el dueño se
    entera por aquí. No emite ningún token: un tercero no puede anular así los
    enlaces pendientes del dueño; el reset lo pide el dueño si lo necesita."""
    if not user.active:
        return
    send_account_email(
        user,
        "You already have a TorqueTrack account",
        format_html(
            "<p>Someone tried to create a TorqueTrack account with this email, but "
            "you already have one.</p>"
            '<p><a href="{}">Sign in to your account</a></p>'
            '<p>Forgot your password? <a href="{}">Reset it here</a>.</p>'
            "<p>If this was not you, you can ignore this email; your account has "
            "not changed.</p>",
            app_url("/login"),
            app_url("/forgot-password"),
        ),
    )


def resend_verification_email(user: User) -> dict:
    if user.email_verified_at is not None:
        return {"ok": True, "emailVerified": True}
    send_verification_email(user)
    return {"ok": True, "emailVerified": False}


def consume_email_verification(token) -> User | None:
    """Marca el email como verificado y consume los enlaces pendientes, o
    devuelve `None`. Debe correr dentro de la transacción de quien llama, que
    en la misma transacción vincula el historial de compras."""
    record = lock_account_token(token, AccountToken.EMAIL_VERIFICATION)
    if record is None:
        return None
    now = timezone.now()
    user = record.user
    user.email_verified_at = user.email_verified_at or now
    user.save(update_fields=["email_verified_at"])
    AccountToken.objects.filter(
        user=user, purpose=AccountToken.EMAIL_VERIFICATION, used_at__isnull=True
    ).update(used_at=now)
    return user
